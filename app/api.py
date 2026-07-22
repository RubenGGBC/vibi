"""API consumida por la PWA."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from . import auth, db, events, projects, tasks
from .claude_models import ClaudeModel, DEFAULT_CLAUDE_MODEL
from .config import settings
from .core import messages as message_core
from .executors import groq_speech
from .serializers import serializar_mensaje, serializar_tarea

log = logging.getLogger("morgana.api")

SUPPORTED_VOICE_TYPES = {
    "audio/flac",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-wav",
}

EstadoTarea = Literal[
    "pendiente",
    "planificando",
    "esperando_aprobacion",
    "ejecutando",
    "completada",
    "rechazada",
    "error",
]


class LoginBody(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    contraseña: str = Field(min_length=1, max_length=200)


class MensajeBody(BaseModel):
    texto: str = Field(min_length=1, max_length=20_000)
    modelo: ClaudeModel = DEFAULT_CLAUDE_MODEL
    client_ref: str | None = Field(default=None, min_length=1, max_length=100)


class ClonarBody(BaseModel):
    url: str = Field(min_length=1, max_length=2_000)


auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
api_router = APIRouter(
    prefix="/api",
    tags=["pwa"],
    dependencies=[Depends(auth.current_user)],
)


def _owned_task(task_id: str, user_id: str) -> dict:
    task = db.get_task(task_id)
    if not task or task["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


@auth_router.post("/login")
async def login(body: LoginBody):
    user = db.get_user_by_nombre(body.nombre)
    if not user or not user.get("password_hash") or not auth.verify_password(
        body.contraseña, user["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    try:
        token = auth.create_access_token(user["id"])
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    db.log_event("login_pwa", user["id"])
    return {"token": token}


@api_router.get("/yo")
async def yo(user: dict = Depends(auth.current_user)):
    return {"id": user["id"], "nombre": user["nombre"]}


@api_router.get("/conversations/active/messages")
async def mensajes_conversacion_activa(
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, ge=1),
    after_id: int | None = Query(None, ge=1),
    user: dict = Depends(auth.current_user),
):
    if before_id is not None and after_id is not None:
        raise HTTPException(
            status_code=400,
            detail="before_id y after_id son mutuamente excluyentes",
        )
    page = db.conversation_messages_page(
        user["id"], limit, before_id, after_id
    )
    page["messages"] = [
        serializar_mensaje(message) for message in page["messages"]
    ]
    return page


@api_router.post("/conversations/reset")
async def resetear_conversacion(user: dict = Depends(auth.current_user)):
    conversation = db.reset_active_conversation(user["id"])
    db.log_event(
        "conversacion_reiniciada",
        user["id"],
        conversation_id=conversation["id"],
    )
    await events.conversacion_reiniciada(user["id"], conversation)
    return {
        "conversation_id": conversation["id"],
        "conversation_created_at": conversation["created_at"],
        "conversation_changed": True,
        "messages": [],
    }


@api_router.get("/tareas")
async def listar_tareas(
    estado: EstadoTarea | None = None,
    proyecto: str | None = None,
    limite: int = Query(50, ge=1, le=200),
    user: dict = Depends(auth.current_user),
):
    return [
        serializar_tarea(task)
        for task in db.list_tasks(user["id"], estado, proyecto, limite)
    ]


@api_router.get("/tareas/{task_id}")
async def ver_tarea(task_id: str, user: dict = Depends(auth.current_user)):
    return serializar_tarea(_owned_task(task_id, user["id"]))


@api_router.post("/tareas/{task_id}/aprobar")
async def aprobar_tarea(task_id: str, user: dict = Depends(auth.current_user)):
    task = _owned_task(task_id, user["id"])
    if task["estado"] != "esperando_aprobacion":
        raise HTTPException(status_code=409, detail="La tarea no espera aprobación")
    if not await tasks.aprobar_tarea(task_id):
        raise HTTPException(status_code=409, detail="La tarea ya fue actualizada")
    return {"ok": True, "task": serializar_tarea(db.get_task(task_id))}


@api_router.post("/tareas/{task_id}/rechazar")
async def rechazar_tarea(task_id: str, user: dict = Depends(auth.current_user)):
    task = _owned_task(task_id, user["id"])
    if task["estado"] != "esperando_aprobacion":
        raise HTTPException(status_code=409, detail="La tarea no espera aprobación")
    if not await tasks.rechazar_tarea(task_id):
        raise HTTPException(status_code=409, detail="La tarea ya fue actualizada")
    return {"ok": True, "task": serializar_tarea(db.get_task(task_id))}


@api_router.post("/mensaje")
async def mensaje(body: MensajeBody, user: dict = Depends(auth.current_user)):
    result = await message_core.procesar_mensaje(
        user,
        body.texto,
        canal="pwa",
        modelo=body.modelo,
        client_ref=body.client_ref,
    )
    if result.via == "rapida":
        return {"via": "rapida", "respuesta": result.respuesta}
    if result.task:
        return {"via": "agentica", "task_id": result.task["id"]}

    resolution = result.resolucion
    if not resolution or resolution.estado == "sin_proyectos":
        raise HTTPException(
            status_code=409,
            detail="No hay proyectos. Clona uno antes de crear una tarea.",
        )
    if resolution.estado == "requiere_proyecto":
        available = ", ".join(resolution.proyectos)
        raise HTTPException(
            status_code=409,
            detail=f"Indica el proyecto en el mensaje. Disponibles: {available}",
        )
    suggestions = ", ".join(resolution.sugerencias or resolution.proyectos)
    raise HTTPException(
        status_code=400,
        detail=f"Proyecto no encontrado. Disponibles: {suggestions}",
    )


@api_router.post("/voz")
async def voz(
    audio: UploadFile = File(...),
    user: dict = Depends(auth.current_user),
):
    """Transcribe un clip corto y lo procesa como un mensaje de Morgana."""
    content_type = (audio.content_type or "").split(";", 1)[0].lower()
    if content_type not in SUPPORTED_VOICE_TYPES:
        raise HTTPException(status_code=415, detail="Formato de audio no compatible")

    content = await audio.read(settings.voice_max_audio_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="El audio está vacío")
    if len(content) > settings.voice_max_audio_bytes:
        raise HTTPException(status_code=413, detail="El audio es demasiado grande")

    try:
        transcript = await groq_speech.transcribir(
            audio.filename or "voz.webm", content
        )
    except Exception as error:
        log.warning("No se pudo transcribir el audio: %s", error)
        raise HTTPException(
            status_code=502,
            detail="No he podido transcribir el audio. Inténtalo de nuevo.",
        ) from error

    if not transcript:
        raise HTTPException(status_code=422, detail="No he detectado voz")

    result = await message_core.procesar_mensaje(
        user, transcript, canal="cara"
    )
    if result.via == "rapida":
        return {
            "via": "rapida",
            "transcripcion": transcript,
            "respuesta": result.respuesta,
        }
    if result.task:
        return {
            "via": "agentica",
            "transcripcion": transcript,
            "task_id": result.task["id"],
            "respuesta": (
                "He creado la tarea y seguiré trabajando en segundo plano."
            ),
        }

    resolution = result.resolucion
    if not resolution or resolution.estado == "sin_proyectos":
        raise HTTPException(
            status_code=409,
            detail="No hay proyectos. Clona uno antes de crear una tarea.",
        )
    if resolution.estado == "requiere_proyecto":
        available = ", ".join(resolution.proyectos)
        raise HTTPException(
            status_code=409,
            detail=f"Indica el proyecto en el mensaje. Disponibles: {available}",
        )
    suggestions = ", ".join(resolution.sugerencias or resolution.proyectos)
    raise HTTPException(
        status_code=400,
        detail=f"Proyecto no encontrado. Disponibles: {suggestions}",
    )


@api_router.get("/proyectos")
async def listar_proyectos(user: dict = Depends(auth.current_user)):
    return {"proyectos": tasks.listar_proyectos(user["id"])}


@api_router.post("/proyectos/clonar", status_code=status.HTTP_201_CREATED)
async def clonar_proyecto(body: ClonarBody, user: dict = Depends(auth.current_user)):
    try:
        name = await projects.clonar_proyecto(user["id"], body.url)
    except projects.ProjectExists as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except projects.InvalidRepoUrl as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except projects.CloneFailed as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    db.log_event("proyecto_clonado", user["id"], proyecto=name, url=body.url)
    return {"proyecto": name}

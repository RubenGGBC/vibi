"""API consumida por la PWA."""
import logging
import re
import time
import unicodedata
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr

from . import (
    activity,
    ai_providers,
    auth,
    db,
    events,
    files,
    nodes,
    projects,
    skills,
    tasks,
    tools,
)
from .claude_models import ClaudeModel
from .config import settings
from .core import messages as message_core
from .executors import claude_chat, edge_speech, groq_speech
from .serializers import serializar_archivo, serializar_mensaje, serializar_tarea

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
CategoriaActividad = Literal[
    "tareas",
    "conversacion",
    "archivos",
    "proyectos",
    "herramientas",
    "cuenta",
    "dispositivos",
]


class LoginBody(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    contraseña: str = Field(min_length=1, max_length=200)


class RegistrarNodoBody(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    contraseña: str = Field(min_length=1, max_length=200)
    nodo: str = Field(min_length=1, max_length=80)
    plataforma: str = Field(min_length=1, max_length=60)


class MensajeBody(BaseModel):
    texto: str = Field(min_length=1, max_length=20_000)
    modelo: ClaudeModel | None = None
    client_ref: str | None = Field(default=None, min_length=1, max_length=100)
    tool_ids: list[str] = Field(default_factory=list, max_length=8)


class ThinkingBody(BaseModel):
    enabled: bool


class TtsBody(BaseModel):
    # El límite real es settings.tts_max_chars; esto solo acota el cuerpo.
    texto: str = Field(max_length=20_000)


class CerrarConversacionVozBody(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64)


class ClonarBody(BaseModel):
    url: str = Field(min_length=1, max_length=2_000)


class CrearHerramientaBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1_000)
    primitive_id: str = Field(min_length=1, max_length=120)
    scope: Literal["personal", "lab"] = "personal"
    bound_arguments: dict = Field(default_factory=dict)


class EjecutarHerramientaBody(BaseModel):
    arguments: dict = Field(default_factory=dict)


class ActivarHerramientaBody(BaseModel):
    enabled: bool


class GuardarSkillBody(BaseModel):
    name: str = Field(default="", max_length=120)
    slug: str | None = Field(default=None, max_length=64)
    description: str = Field(default="", max_length=1_000)
    instructions: str = Field(default="", max_length=8_000)
    examples: list[str] = Field(default_factory=list, max_length=5)
    tool_ids: list[str] = Field(default_factory=list, max_length=4)
    scope: Literal["personal", "lab"] = "personal"


class ActivarSkillBody(BaseModel):
    enabled: bool


class ProbarSkillBody(BaseModel):
    input: str = Field(min_length=1, max_length=20_000)


class ConfiguracionIABody(BaseModel):
    chat_provider: Literal["anthropic", "groq"]
    chat_model: str = Field(min_length=1, max_length=120)
    tools_provider: Literal["anthropic", "groq"]
    tools_model: str = Field(min_length=1, max_length=120)
    speech_provider: Literal["groq"]
    speech_model: str = Field(min_length=1, max_length=120)
    agent_provider: Literal["anthropic"]
    agent_model: ClaudeModel
    anthropic_api_key: SecretStr | None = Field(default=None, max_length=500)
    groq_api_key: SecretStr | None = Field(default=None, max_length=500)
    clear_anthropic_api_key: bool = False
    clear_groq_api_key: bool = False


auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
api_router = APIRouter(
    prefix="/api",
    tags=["pwa"],
    dependencies=[Depends(auth.current_user)],
)
voice_router = APIRouter(prefix="/api", tags=["voz"])


def _normalizar_orden_voz(texto: str) -> str:
    sin_tildes = "".join(
        caracter
        for caracter in unicodedata.normalize("NFKD", texto.casefold())
        if not unicodedata.combining(caracter)
    )
    return " ".join(re.findall(r"[a-z0-9]+", sin_tildes))


ORDENES_CERRAR_CONVERSACION = {"adios morgana", "gracias morgana"}


def _conversacion_voz_activa(user: dict, conversation_id: str) -> dict:
    """Valida que un turno pertenece a la invocación de voz que sigue abierta."""
    current = db.get_active_conversation(user["id"])
    if not conversation_id or not current or current["id"] != conversation_id:
        raise HTTPException(
            status_code=409,
            detail="Esta invocación de Morgana ya terminó. Vuelve a invocarla.",
        )
    return current


async def _reiniciar_conversacion(
    user: dict,
    motivo: str,
    expected_conversation_id: str | None = None,
) -> dict:
    """Archiva la conversación activa y deja una vacía lista para el próximo turno."""
    current = db.get_active_conversation(user["id"])
    if expected_conversation_id and (
        not current or current["id"] != expected_conversation_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Esta invocación de Morgana ya terminó. Vuelve a invocarla.",
        )
    if current:
        await claude_chat.close_session(current["id"])
    conversation = db.reset_active_conversation(
        user["id"], expected_conversation_id
    )
    if not conversation:
        raise HTTPException(
            status_code=409,
            detail="Esta invocación de Morgana ya terminó. Vuelve a invocarla.",
        )
    db.log_event(
        motivo,
        user["id"],
        conversation_id=conversation["id"],
    )
    await events.conversacion_reiniciada(user["id"], conversation)
    return conversation


def _owned_task(task_id: str, user_id: str) -> dict:
    task = db.get_task(task_id)
    if not task or task["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


def _skill_payload(body: GuardarSkillBody) -> dict:
    return body.model_dump()


def _raise_skill_http(error: Exception, *, activation: bool = False) -> None:
    if isinstance(error, skills.SkillNotFound):
        code = 404
    elif isinstance(error, skills.SkillForbidden):
        code = 403
    elif isinstance(error, skills.SkillConflict):
        code = 409
    elif isinstance(error, skills.SkillRunError):
        code = 502
    elif isinstance(error, skills.InvalidSkill):
        code = 409 if activation else 422
    else:
        code = 400
    raise HTTPException(status_code=code, detail=str(error)) from error


def _autenticar(nombre: str, contraseña: str) -> dict:
    user = db.get_user_by_nombre(nombre)
    if not user or not user.get("password_hash") or not auth.verify_password(
        contraseña, user["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    return user


@auth_router.post("/login")
async def login(body: LoginBody):
    user = _autenticar(body.nombre, body.contraseña)
    try:
        token = auth.create_access_token(user["id"])
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    db.log_event("login_pwa", user["id"])
    return {"token": token}


@auth_router.post("/nodos")
async def registrar_nodo(body: RegistrarNodoBody):
    """Alta de una máquina ejecutora.

    Es el único sitio donde el agente usa tus credenciales: a cambio recibe un
    token propio de ese nodo y olvida la contraseña. Revocar el nodo no afecta
    al resto de tus dispositivos.
    """
    user = _autenticar(body.nombre, body.contraseña)
    try:
        node, token = nodes.register(user, body.nodo, body.plataforma)
    except db.NodeNameTaken as error:
        raise HTTPException(
            status_code=409,
            detail=f"Ya tienes un dispositivo llamado «{body.nodo}»",
        ) from error
    except nodes.NodeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"token": token, "nodo": nodes.serialize(node, online=False)}


@api_router.get("/nodos")
def listar_nodos(user: dict = Depends(auth.current_user)):
    return {
        "nodos": [nodes.serialize(node) for node in db.list_nodes(user["id"])]
    }


@api_router.post("/nodos/{node_id}/revocar")
def revocar_nodo(node_id: str, user: dict = Depends(auth.current_user)):
    node = db.revoke_node(node_id, user["id"])
    if not node:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    db.log_event("nodo_revocado", user["id"], node_id=node_id)
    return {"nodo": nodes.serialize(node, online=False)}


@api_router.get("/nodos/{node_id}/ordenes")
def listar_ordenes_nodo(
    node_id: str,
    limite: int = Query(20, ge=1, le=100),
    user: dict = Depends(auth.current_user),
):
    if not db.get_node_for_user(node_id, user["id"]):
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    ordenes = db.list_node_orders(node_id, user["id"], limite)
    return {
        "ordenes": [
            {
                "id": orden["id"],
                "capacidad": orden["capability"],
                "estado": orden["estado"],
                "creada_en": orden["created_at"],
                "completada_en": orden["completed_at"],
            }
            for orden in ordenes
        ]
    }


@api_router.get("/yo")
async def yo(user: dict = Depends(auth.current_user)):
    return {"id": user["id"], "nombre": user["nombre"]}


@api_router.get("/actividad")
def ver_actividad(
    limite: int = Query(25, ge=1, le=100),
    antes_de: int | None = Query(None, ge=1),
    categoria: CategoriaActividad | None = None,
    user: dict = Depends(auth.current_user),
):
    event_types = activity.CATEGORY_EVENT_TYPES.get(categoria, ()) if categoria else ()
    rows, next_cursor = db.list_events_for_user(
        user["id"], limite, antes_de, event_types
    )
    summary = db.activity_summary(user["id"], time.time() - 120)
    return {
        "resumen": {
            "tareas_activas": summary["active_tasks"],
            "esperando_aprobacion": summary["awaiting_approval"],
            "tareas_completadas": summary["completed_tasks"],
            "almacenamiento_usado_bytes": summary["managed_storage_bytes"],
            "almacenamiento_cuota_bytes": settings.file_user_quota_bytes,
            "dispositivos_conocidos": summary["known_devices"],
            "dispositivos_recientes": summary["recent_devices"],
        },
        "eventos": [
            activity.serialize_event(event, user["id"]) for event in rows
        ],
        "siguiente_cursor": next_cursor,
    }


@api_router.get("/configuracion/ia")
def ver_configuracion_ia(user: dict = Depends(auth.current_user)):
    return ai_providers.public_settings(user["id"])


@api_router.put("/configuracion/ia")
def actualizar_configuracion_ia(
    body: ConfiguracionIABody,
    user: dict = Depends(auth.current_user),
):
    values = ai_providers.AISettings(
        chat_provider=body.chat_provider,
        chat_model=body.chat_model.strip(),
        tools_provider=body.tools_provider,
        tools_model=body.tools_model.strip(),
        speech_provider=body.speech_provider,
        speech_model=body.speech_model.strip(),
        agent_provider=body.agent_provider,
        agent_model=body.agent_model.strip(),
    )
    supplied_keys = {
        "anthropic": body.anthropic_api_key.get_secret_value()
        if body.anthropic_api_key
        else None,
        "groq": body.groq_api_key.get_secret_value() if body.groq_api_key else None,
    }
    if any(key is not None and len(key.strip()) < 8 for key in supplied_keys.values()):
        raise HTTPException(status_code=400, detail="La API key es demasiado corta")
    try:
        for provider, key in supplied_keys.items():
            if key:
                ai_providers.set_api_key(user["id"], provider, key)
        if body.clear_anthropic_api_key:
            ai_providers.delete_api_key(user["id"], "anthropic")
        if body.clear_groq_api_key:
            ai_providers.delete_api_key(user["id"], "groq")
        ai_providers.save_settings(user["id"], values)
    except ai_providers.ProviderConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.log_event(
        "configuracion_ia_actualizada",
        user["id"],
        chat_provider=values.chat_provider,
        tools_provider=values.tools_provider,
        speech_provider=values.speech_provider,
        agent_provider=values.agent_provider,
    )
    return ai_providers.public_settings(user["id"])


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
    conversation = await _reiniciar_conversacion(user, "conversacion_reiniciada")
    return {
        "conversation_id": conversation["id"],
        "conversation_created_at": conversation["created_at"],
        "conversation_changed": True,
        "thinking_enabled": bool(conversation.get("thinking_enabled")),
        "messages": [],
    }


@api_router.post("/conversations/active/thinking")
async def actualizar_thinking(
    body: ThinkingBody,
    user: dict = Depends(auth.current_user),
):
    conversation = db.set_active_conversation_thinking(user["id"], body.enabled)
    await claude_chat.close_session(conversation["id"])
    db.log_event(
        "conversation_thinking_changed",
        user["id"],
        conversation_id=conversation["id"],
        enabled=body.enabled,
    )
    return {
        "conversation_id": conversation["id"],
        "thinking_enabled": bool(conversation["thinking_enabled"]),
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


@api_router.post(
    "/tareas/{task_id}/reintentar",
    status_code=status.HTTP_201_CREATED,
)
async def reintentar_tarea(
    task_id: str, user: dict = Depends(auth.current_user)
):
    original = _owned_task(task_id, user["id"])
    if original["estado"] != "error":
        raise HTTPException(
            status_code=409,
            detail="Solo se pueden reintentar tareas con error",
        )
    try:
        retried = await tasks.encolar_tarea(
            user["id"],
            user["nombre"],
            original["prompt"],
            original["workspace"],
            original["modelo"],
        )
    except (OSError, TypeError, ValueError):
        raise HTTPException(
            status_code=409,
            detail="El proyecto original ya no está disponible",
        ) from None
    db.log_event(
        "tarea_reintentada",
        user["id"],
        source_task_id=original["id"],
        task_id=retried["id"],
    )
    return {
        "ok": True,
        "task": serializar_tarea(retried),
        "source_task_id": original["id"],
    }


@api_router.post("/mensaje")
async def mensaje(body: MensajeBody, user: dict = Depends(auth.current_user)):
    result = await message_core.procesar_mensaje(
        user,
        body.texto,
        canal="pwa",
        modelo=body.modelo,
        client_ref=body.client_ref,
        tool_ids=tuple(body.tool_ids),
    )
    if result.via == "rapida":
        return {"via": "rapida", "respuesta": result.respuesta}
    if result.via == "herramienta":
        return {
            "via": "herramienta",
            "respuesta": result.respuesta,
            "artifacts": result.artifacts,
        }
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


@voice_router.post("/voz/abrir")
async def abrir_conversacion_voz(user: dict = Depends(auth.current_voice_user)):
    """Crea el hilo que vivirá exactamente durante esta invocación de Morgana."""
    conversation = await _reiniciar_conversacion(
        user, "conversacion_voz_abierta"
    )
    return {"conversation_id": conversation["id"]}


@voice_router.post("/voz")
async def voz(
    audio: UploadFile = File(...),
    client_ref: str = Form("", max_length=200),
    conversation_mode: bool = Form(False),
    conversation_id: str = Form("", max_length=64),
    user: dict = Depends(auth.current_voice_user),
):
    """Transcribe un clip corto y lo procesa como un mensaje de Morgana."""
    content_type = (audio.content_type or "").split(";", 1)[0].lower()
    if content_type not in SUPPORTED_VOICE_TYPES:
        raise HTTPException(status_code=415, detail="Formato de audio no compatible")

    voice_conversation_id: str | None = None
    if conversation_mode:
        voice_conversation_id = conversation_id.strip()
        _conversacion_voz_activa(user, voice_conversation_id)

    content = await audio.read(settings.voice_max_audio_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="El audio está vacío")
    if len(content) > settings.voice_max_audio_bytes:
        raise HTTPException(status_code=413, detail="El audio es demasiado grande")

    try:
        transcript = await groq_speech.transcribir(
            user["id"], audio.filename or "voz.webm", content
        )
    except Exception as error:
        log.warning("No se pudo transcribir el audio: %s", error)
        raise HTTPException(
            status_code=502,
            detail="No he podido transcribir el audio. Inténtalo de nuevo.",
        ) from error

    if not transcript:
        raise HTTPException(status_code=422, detail="No he detectado voz")

    if (
        conversation_mode
        and _normalizar_orden_voz(transcript) in ORDENES_CERRAR_CONVERSACION
    ):
        db.log_event("conversacion_voz_cerrada", user["id"])
        # La despedida termina la sesión: el hilo no debe sobrevivir al cierre.
        await _reiniciar_conversacion(
            user,
            "conversacion_voz_reiniciada",
            expected_conversation_id=voice_conversation_id,
        )
        return {
            "via": "cerrar",
            "transcripcion": transcript,
            "respuesta": "",
        }

    # El client_ref identifica el turno en los eventos: así la cara puede ir
    # locutando los fragmentos según llegan, sin esperar a esta respuesta.
    try:
        result = await message_core.procesar_mensaje(
            user,
            transcript,
            canal="cara",
            client_ref=client_ref.strip() or None,
            conversation_id=voice_conversation_id,
        )
    except claude_chat.ConversationChanged as error:
        raise HTTPException(
            status_code=409,
            detail="Esta invocación de Morgana ya terminó. Vuelve a invocarla.",
        ) from error
    if result.via == "rapida":
        return {
            "via": "rapida",
            "transcripcion": transcript,
            "respuesta": result.respuesta,
        }
    if result.via == "herramienta":
        return {
            "via": "herramienta",
            "transcripcion": transcript,
            "respuesta": result.respuesta,
            "artifacts": result.artifacts,
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


@voice_router.post("/voz/cerrar")
async def cerrar_conversacion_voz(
    body: CerrarConversacionVozBody | None = None,
    user: dict = Depends(auth.current_voice_user),
):
    """Cierra la sesión de la cara: la próxima invocación empieza de cero.

    Vive en el router de voz porque la app de escritorio se autentica con el
    token revocable del nodo, que no vale para el resto de la API.
    """
    expected = body.conversation_id if body else None
    current = db.get_active_conversation(user["id"])
    if expected and (not current or current["id"] != expected):
        return {
            "cerrada": False,
            "conversation_id": current["id"] if current else None,
        }
    try:
        conversation = await _reiniciar_conversacion(
            user,
            "conversacion_voz_reiniciada",
            expected_conversation_id=expected,
        )
    except HTTPException as error:
        if expected and error.status_code == 409:
            current = db.get_active_conversation(user["id"])
            return {
                "cerrada": False,
                "conversation_id": current["id"] if current else None,
            }
        raise
    return {"cerrada": True, "conversation_id": conversation["id"]}


@voice_router.post("/tts")
async def tts(body: TtsBody, user: dict = Depends(auth.current_voice_user)):
    """Locuta un fragmento de texto con una voz neuronal y devuelve el MP3."""
    if not settings.tts_enabled:
        raise HTTPException(
            status_code=503, detail="La síntesis de voz está desactivada"
        )

    texto = body.texto.strip()
    if not texto:
        raise HTTPException(status_code=400, detail="No hay texto que sintetizar")
    if len(texto) > settings.tts_max_chars:
        raise HTTPException(status_code=413, detail="El texto es demasiado largo")

    try:
        audio = await edge_speech.sintetizar(texto)
    except Exception as error:
        log.warning("No se pudo sintetizar la voz: %s", error)
        raise HTTPException(
            status_code=502, detail="No he podido generar la voz"
        ) from error

    return Response(content=audio, media_type="audio/mpeg")


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


@api_router.delete("/proyectos/{name}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_proyecto(name: str, user: dict = Depends(auth.current_user)):
    try:
        removed = projects.eliminar_proyecto(user["id"], name)
    except projects.ProjectNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except projects.ProjectInUse as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except projects.DeleteFailed as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    db.log_event("proyecto_eliminado", user["id"], proyecto=removed)


@api_router.get("/archivos")
def listar_archivos(
    consulta: str = Query("", max_length=500),
    ruta: str = Query("", max_length=1000),
    limite: int = Query(50, ge=1, le=100),
    user: dict = Depends(auth.current_user),
):
    if consulta.strip():
        found = files.search_files(user["id"], consulta, limite)
        return {
            "ruta": ruta,
            "carpetas": [],
            "archivos": [serializar_archivo(file) for file in found],
        }
    try:
        folders, found = files.list_directory(user["id"], ruta, limite)
    except files.UnsafeFilePath as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except files.FileServiceError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return {
        "ruta": ruta,
        "carpetas": folders,
        "archivos": [serializar_archivo(file) for file in found],
    }


@api_router.post("/archivos", status_code=status.HTTP_201_CREATED)
async def subir_archivo(
    archivo: UploadFile = File(...),
    user: dict = Depends(auth.current_user),
):
    try:
        stored = await files.store_upload(user["id"], archivo)
    except files.FileTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except files.FileQuotaExceeded as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except files.FileServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.log_event(
        "archivo_subido",
        user["id"],
        file_id=stored["id"],
        size_bytes=stored["size_bytes"],
    )
    await events.archivo_actualizado(user["id"], stored)
    return serializar_archivo(stored)


@api_router.get("/archivos/{file_id}/contenido")
async def descargar_archivo(
    file_id: str,
    user: dict = Depends(auth.current_user),
):
    file = db.get_file_for_user(file_id, user["id"])
    if not file:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    try:
        path = files.path_for_file(file, user["id"])
    except files.UnsafeFilePath as error:
        raise HTTPException(status_code=404, detail="Archivo no encontrado") from error
    db.log_event("archivo_descargado", user["id"], file_id=file_id)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=file["name"],
        headers={"Cache-Control": "private, no-store"},
    )


@api_router.delete("/archivos/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_archivo(
    file_id: str,
    user: dict = Depends(auth.current_user),
):
    if not files.delete_managed_file(user["id"], file_id):
        raise HTTPException(
            status_code=404,
            detail="Archivo no encontrado o no gestionado por Morgana",
        )
    db.log_event("archivo_eliminado", user["id"], file_id=file_id)
    await events.archivo_eliminado(user["id"], file_id)


@api_router.get("/herramientas")
async def listar_herramientas(user: dict = Depends(auth.current_user)):
    return {
        "herramientas": tools.list_catalog(user["id"], bool(user.get("is_admin")))
    }


@api_router.post("/herramientas", status_code=status.HTTP_201_CREATED)
async def crear_herramienta(
    body: CrearHerramientaBody,
    user: dict = Depends(auth.current_user),
):
    try:
        tool = tools.create_custom_tool(
            user,
            body.name,
            body.description,
            body.primitive_id,
            body.scope,
            body.bound_arguments,
        )
    except tools.ToolNotFound as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except tools.InvalidToolArguments as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except tools.ToolError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    db.log_event(
        "herramienta_creada", user["id"], tool_id=tool["id"], scope=tool["scope"]
    )
    return tool


@api_router.put("/herramientas/{tool_id}")
async def actualizar_herramienta(
    tool_id: str,
    body: CrearHerramientaBody,
    user: dict = Depends(auth.current_user),
):
    try:
        tool = tools.update_custom_tool(
            tool_id,
            user,
            body.name,
            body.description,
            body.primitive_id,
            body.scope,
            body.bound_arguments,
        )
    except tools.ToolNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except tools.InvalidToolArguments as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except tools.ToolPermissionDenied as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    db.log_event(
        "herramienta_actualizada", user["id"], tool_id=tool["id"], scope=tool["scope"]
    )
    return tool


@api_router.post(
    "/herramientas/{tool_id}/duplicar", status_code=status.HTTP_201_CREATED
)
async def duplicar_herramienta(
    tool_id: str,
    user: dict = Depends(auth.current_user),
):
    try:
        tool = tools.duplicate_tool(tool_id, user)
    except tools.ToolNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except tools.ToolDisabled as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.log_event(
        "herramienta_duplicada", user["id"], tool_id=tool["id"], source_tool_id=tool_id
    )
    return tool


@api_router.get("/herramientas/{tool_id}/invocaciones")
async def listar_invocaciones_herramienta(
    tool_id: str,
    limite: int = Query(default=25, ge=1, le=100),
    user: dict = Depends(auth.current_user),
):
    try:
        invocations = tools.list_invocations(tool_id, user, limite)
    except tools.ToolNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"invocations": invocations}


@api_router.post("/herramientas/{tool_id}/ejecutar")
async def ejecutar_herramienta(
    tool_id: str,
    body: EjecutarHerramientaBody,
    user: dict = Depends(auth.current_user),
):
    try:
        return await tools.execute(tool_id, user, body.arguments)
    except tools.ToolNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except tools.ToolDisabled as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except tools.InvalidToolArguments as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (files.FileTooLarge, files.FileQuotaExceeded) as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except files.FileServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@api_router.post("/herramientas/{tool_id}/estado")
async def cambiar_estado_herramienta(
    tool_id: str,
    body: ActivarHerramientaBody,
    user: dict = Depends(auth.current_user),
):
    try:
        updated = tools.set_enabled(tool_id, user, body.enabled)
    except tools.ToolNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except tools.ToolPermissionDenied as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    db.log_event(
        "herramienta_activada" if body.enabled else "herramienta_desactivada",
        user["id"],
        tool_id=tool_id,
        scope=updated["scope"],
    )
    return updated


@api_router.get("/skills")
def listar_skills(user: dict = Depends(auth.current_user)):
    visible = skills.list_visible(user)
    return {
        "skills": visible,
        "summary": {
            "active": sum(skill["enabled"] for skill in visible),
            "drafts": sum(not skill["enabled"] for skill in visible),
        },
        "available_tools": tools.list_catalog(
            user["id"], bool(user.get("is_admin"))
        ),
    }


@api_router.post("/skills", status_code=status.HTTP_201_CREATED)
def crear_skill(
    body: GuardarSkillBody,
    user: dict = Depends(auth.current_user),
):
    try:
        created = skills.create_skill(user, _skill_payload(body))
    except skills.SkillError as error:
        _raise_skill_http(error)
    db.log_event(
        "skill_created",
        user["id"],
        skill_id=created["id"],
        scope=created["scope"],
        version=created["version"],
    )
    return created


@api_router.put("/skills/{skill_id}")
def actualizar_skill(
    skill_id: str,
    body: GuardarSkillBody,
    user: dict = Depends(auth.current_user),
):
    try:
        updated = skills.update_skill(user, skill_id, _skill_payload(body))
    except skills.SkillError as error:
        _raise_skill_http(error)
    db.log_event(
        "skill_updated",
        user["id"],
        skill_id=updated["id"],
        scope=updated["scope"],
        version=updated["version"],
    )
    return updated


@api_router.post("/skills/{skill_id}/estado")
def cambiar_estado_skill(
    skill_id: str,
    body: ActivarSkillBody,
    user: dict = Depends(auth.current_user),
):
    try:
        updated = skills.set_enabled(user, skill_id, body.enabled)
    except skills.SkillError as error:
        _raise_skill_http(error, activation=True)
    db.log_event(
        "skill_enabled" if body.enabled else "skill_disabled",
        user["id"],
        skill_id=updated["id"],
        scope=updated["scope"],
        version=updated["version"],
    )
    return updated


@api_router.post(
    "/skills/{skill_id}/duplicar",
    status_code=status.HTTP_201_CREATED,
)
def duplicar_skill(skill_id: str, user: dict = Depends(auth.current_user)):
    try:
        duplicate = skills.duplicate_skill(user, skill_id)
    except skills.SkillError as error:
        _raise_skill_http(error)
    db.log_event(
        "skill_duplicated",
        user["id"],
        skill_id=duplicate["id"],
        source_skill_id=skill_id,
        scope=duplicate["scope"],
        version=duplicate["version"],
    )
    return duplicate


@api_router.get("/skills/{skill_id}/versiones")
def listar_versiones_skill(
    skill_id: str, user: dict = Depends(auth.current_user)
):
    try:
        return skills.list_versions(user, skill_id)
    except skills.SkillError as error:
        _raise_skill_http(error)


@api_router.get("/skills/{skill_id}/exportar")
def exportar_skill(skill_id: str, user: dict = Depends(auth.current_user)):
    try:
        return skills.export_skill(user, skill_id)
    except skills.SkillError as error:
        _raise_skill_http(error)


@api_router.post("/skills/{skill_id}/probar")
async def probar_skill(
    skill_id: str,
    body: ProbarSkillBody,
    user: dict = Depends(auth.current_user),
):
    try:
        return await skills.run_skill(
            user, skill_id, body.input, allow_draft=True
        )
    except skills.SkillError as error:
        _raise_skill_http(error)
    except tools.ToolNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except tools.ToolDisabled as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (tools.InvalidToolArguments, files.FileServiceError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

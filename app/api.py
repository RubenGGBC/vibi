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
    forja,
    nodes,
    perfil,
    perfil_metricas,
    projects,
    skills,
    taint,
    tasks,
    tools,
)
from .claude_models import ClaudeModel
from .config import settings
from .core import messages as message_core
from .executors import chat, edge_speech, groq_speech
from .serializers import serializar_archivo, serializar_mensaje, serializar_tarea

log = logging.getLogger("vibi.api")

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


class EjecucionBody(BaseModel):
    habilitada: bool


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


class ForjarHerramientaBody(BaseModel):
    peticion: str = Field(min_length=10, max_length=forja.MAX_PETICION)
    reemplaza: str = Field(default="", max_length=100)


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
    # "antigravity" conversa con la CLI `agy` del usuario; no lleva clave.
    chat_provider: Literal["anthropic", "antigravity"]
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


ORDENES_CERRAR_CONVERSACION = {"adios vibi", "gracias vibi"}


def _conversacion_voz_activa(user: dict, conversation_id: str) -> dict:
    """Valida que un turno pertenece a la invocación de voz que sigue abierta."""
    current = db.get_active_conversation(user["id"])
    if not conversation_id or not current or current["id"] != conversation_id:
        raise HTTPException(
            status_code=409,
            detail="Esta invocación de Vibi ya terminó. Vuelve a invocarla.",
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
            detail="Esta invocación de Vibi ya terminó. Vuelve a invocarla.",
        )
    if current:
        await chat.close_session(current["id"])
    conversation = db.reset_active_conversation(
        user["id"], expected_conversation_id
    )
    if not conversation:
        raise HTTPException(
            status_code=409,
            detail="Esta invocación de Vibi ya terminó. Vuelve a invocarla.",
        )
    db.log_event(
        motivo,
        user["id"],
        conversation_id=conversation["id"],
    )
    # Empezar de cero también borra el rastro de lo que Vibi había leído:
    # el contexto sospechoso se fue con la conversación anterior.
    taint.registro.limpiar(user["id"])
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


@api_router.get("/nodos/aprobaciones")
def listar_aprobaciones(user: dict = Depends(auth.current_user)):
    """Lo que está detenido esperando tu decisión."""
    pendientes = db.list_pending_node_approvals(user["id"])
    nombres = {
        node["id"]: node for node in db.list_nodes(user["id"], include_revoked=True)
    }
    return {
        "ordenes": [
            nodes.serialize_order(orden, nombres.get(orden["node_id"]))
            for orden in pendientes
        ]
    }


@api_router.post("/nodos/ordenes/{order_id}/aprobar")
async def aprobar_orden(order_id: str, user: dict = Depends(auth.current_user)):
    try:
        resultado = await nodes.aprobar(user, order_id)
    except nodes.NodeNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except nodes.ShellDeshabilitado as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except nodes.NodeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return resultado


@api_router.post("/nodos/ordenes/{order_id}/rechazar")
async def rechazar_orden(order_id: str, user: dict = Depends(auth.current_user)):
    try:
        return {"orden": await nodes.rechazar(user, order_id)}
    except nodes.NodeNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@api_router.post("/nodos/{node_id}/ejecucion")
def cambiar_ejecucion_nodo(
    node_id: str,
    body: EjecucionBody,
    user: dict = Depends(auth.current_user),
):
    """Enciende o apaga la ejecución de comandos en una máquina concreta."""
    node = db.set_node_shell(node_id, user["id"], body.habilitada)
    if not node:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    db.log_event(
        "nodo_ejecucion_cambiada",
        user["id"],
        node_id=node_id,
        habilitada=body.habilitada,
    )
    return {"nodo": nodes.serialize(node)}


@api_router.post("/nodos/ejecucion")
def cambiar_ejecucion_global(
    body: EjecucionBody, user: dict = Depends(auth.current_user)
):
    """Kill switch: corta de golpe la ejecución en todas tus máquinas."""
    afectados = db.set_all_nodes_shell(user["id"], body.habilitada)
    db.log_event(
        "nodos_ejecucion_global",
        user["id"],
        habilitada=body.habilitada,
        nodos=afectados,
    )
    return {
        "nodos": [nodes.serialize(node) for node in db.list_nodes(user["id"])],
        "afectados": afectados,
    }


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
    await chat.close_session(conversation["id"])
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
    """Crea el hilo que vivirá exactamente durante esta invocación de Vibi."""
    conversation = await _reiniciar_conversacion(
        user, "conversacion_voz_abierta"
    )
    # Aquí no se monta el motor, y es deliberado. La palabra clave se
    # equivoca —acepta «vibi», «bibi» y «vivi», sílabas que salen sueltas en
    # cualquier conversación— y montarlo abre el navegador del usuario en su
    # ordenador, porque `_process_for` asegura Playwright antes de arrancar
    # `agy`. Medido sobre 48 h: de nueve aperturas del canal, seis no llevaron
    # detrás ningún clip de audio. Eran seis Opera abiertos por un ruido.
    #
    # El precalentado no se pierde, se mueve: lo hace `/voz` en cuanto llega
    # audio de verdad, y sigue solapándose con la transcripción.
    return {"conversation_id": conversation["id"]}


@voice_router.post("/voz")
async def voz(
    audio: UploadFile = File(...),
    client_ref: str = Form("", max_length=200),
    conversation_mode: bool = Form(False),
    conversation_id: str = Form("", max_length=64),
    user: dict = Depends(auth.current_voice_user),
):
    """Transcribe un clip corto y lo procesa como un mensaje de Vibi."""
    content_type = (audio.content_type or "").split(";", 1)[0].lower()
    if content_type not in SUPPORTED_VOICE_TYPES:
        raise HTTPException(status_code=415, detail="Formato de audio no compatible")

    voice_conversation_id: str | None = None
    conversacion_voz: dict | None = None
    if conversation_mode:
        voice_conversation_id = conversation_id.strip()
        conversacion_voz = _conversacion_voz_activa(user, voice_conversation_id)

    content = await audio.read(settings.voice_max_audio_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="El audio está vacío")
    if len(content) > settings.voice_max_audio_bytes:
        raise HTTPException(status_code=413, detail="El audio es demasiado grande")

    # Ahora sí hay voz que atender, así que toca montar el motor. Va antes de
    # transcribir y no después porque el viaje a Groq es el hueco que el
    # precalentado aprovecha, igual que antes aprovechaba lo que tardabas en
    # hablar: se gana lo mismo sin montarlo por un ruido que sonó a «vibi».
    if conversacion_voz is not None:
        chat.precalentar_en_segundo_plano(user, conversacion_voz)

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
    except chat.ConversationChanged as error:
        raise HTTPException(
            status_code=409,
            detail="Esta invocación de Vibi ya terminó. Vuelve a invocarla.",
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
            detail="Archivo no encontrado o no gestionado por Vibi",
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


@api_router.post("/herramientas/forjar", status_code=status.HTTP_201_CREATED)
async def forjar_herramienta(
    body: ForjarHerramientaBody,
    user: dict = Depends(auth.current_user),
):
    """Le encarga a Claude el guion de una herramienta nueva y lo guarda."""
    try:
        forjada = await forja.forjar(
            user, body.peticion, body.reemplaza.strip() or None
        )
    except forja.ManifiestoInvalido as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except forja.ForjaError as error:
        # 502: quien falló fue el modelo, no la petición de quien la pidió.
        raise HTTPException(status_code=502, detail=str(error)) from error
    return forjada


@api_router.get("/herramientas/{tool_id}/guion")
async def ver_guion_herramienta(
    tool_id: str,
    user: dict = Depends(auth.current_user),
):
    """El código de una herramienta forjada, para poder leerlo antes de usarla."""
    script = forja.cargar(tool_id, user["id"])
    if not script:
        raise HTTPException(status_code=404, detail="Herramienta no encontrada")
    return tools.serialize_script_tool(script, con_codigo=True)


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
    except tools.ToolPermissionDenied as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
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
    except tools.ToolExecutionFailed as error:
        # La herramienta corrió y terminó mal: el motivo es lo que hay que
        # enseñar, no un 500 que obliga a ir al log del servidor a buscarlo.
        raise HTTPException(status_code=400, detail=str(error)) from error
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


# ==============================================================================
# Especialización por usuario (Perfil, Observador, Métricas, Entrevista)
# ==============================================================================


class CrearAfirmacionBody(BaseModel):
    clase: str
    valor: str
    procedencia: str = "entrevista"


class AprobarCapacidadBody(BaseModel):
    tipo: str
    referencia: str
    justificacion: str
    transporte: str = ""
    endpoint: str = ""
    # Cómo se lanza uno local («npm:paquete@version»). Viaja desde el registro
    # hasta aquí sin que el cliente lo componga: lo que se aprueba es la
    # versión concreta que se verificó, no «lo último que haya».
    paquete: str = ""


class FijarNivelBody(BaseModel):
    nivel: str


class PropuestaRequest(BaseModel):
    terminos_pedidos: list[str] = Field(default_factory=list)
    terminos_adyacentes: list[str] = Field(default_factory=list)
    texto_libre: str = ""
    # Lo que la persona es, aparte de lo que ha pedido: aficiones y
    # herramientas. Va por separado y no sumado al `texto_libre` porque
    # alimenta el otro bloque, y mezclarlos borraría la diferencia entre «esto
    # me lo has pedido» y «esto además encaja contigo».
    texto_libre_adyacente: str = ""


class CompletarEntrevistaBody(BaseModel):
    afirmaciones: list[CrearAfirmacionBody] = Field(default_factory=list)
    capacidades: list[AprobarCapacidadBody] = Field(default_factory=list)
    resumen: str = ""


class TurnoEntrevistaItem(BaseModel):
    rol: str
    texto: str


class TurnoEntrevistaBody(BaseModel):
    historial: list[TurnoEntrevistaItem] = Field(default_factory=list)


@api_router.get("/perfil")
def obtener_perfil(user: dict = Depends(auth.current_user)):
    user_id = user["id"]
    afirmaciones = perfil.afirmaciones_de(user_id)
    capacidades = perfil.capacidades_de(user_id)
    resumen = perfil.resumen_de(user_id)
    total_propuestas, propuestas_aprobadas = perfil.metricas_propuestas(user_id)
    tasa = perfil_metricas.tasa_de_aceptacion(
        propuestas=total_propuestas, aprobadas=propuestas_aprobadas
    )
    supervivencia = perfil_metricas.supervivencia(user_id, dias=14)
    return {
        "user_id": user_id,
        "resumen": resumen,
        "afirmaciones": afirmaciones,
        "capacidades": capacidades,
        "metricas": {
            "tasa_de_aceptacion": tasa,
            "supervivencia_14dias": supervivencia,
            "total_afirmaciones": len(afirmaciones),
            "total_capacidades": len(capacidades),
        },
    }


@api_router.post("/perfil/afirmaciones")
async def crear_afirmacion(
    body: CrearAfirmacionBody, user: dict = Depends(auth.current_user)
):
    try:
        afirmacion = perfil.afirmar(
            user["id"], body.clase, body.valor, body.procedencia
        )
        from .executors import antigravity_chat  # noqa: PLC0415
        await antigravity_chat.aplicar_perfil(user)
        return afirmacion
    except perfil.PerfilInvalido as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@api_router.delete("/perfil/afirmaciones/{afirmacion_id}")
async def borrar_afirmacion(
    afirmacion_id: int, user: dict = Depends(auth.current_user)
):
    ok = perfil.eliminar_afirmacion(user["id"], afirmacion_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Afirmación no encontrada")
    from .executors import antigravity_chat  # noqa: PLC0415
    await antigravity_chat.aplicar_perfil(user)
    return {"ok": True}


@api_router.post("/perfil/capacidades/aprobar")
async def aprobar_capacidad(
    body: AprobarCapacidadBody, user: dict = Depends(auth.current_user)
):
    try:
        cap = perfil.aprobar_capacidad(
            user["id"],
            body.tipo,
            body.referencia,
            body.justificacion,
            transporte=body.transporte,
            endpoint=body.endpoint,
            paquete=body.paquete,
        )
        from .executors import antigravity_chat  # noqa: PLC0415
        await antigravity_chat.aplicar_perfil(user)
        return cap
    except perfil.PerfilInvalido as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@api_router.put("/perfil/capacidades/{capacidad_id}/nivel")
async def cambiar_nivel_capacidad(
    capacidad_id: int,
    body: FijarNivelBody,
    user: dict = Depends(auth.current_user),
):
    try:
        ok = perfil.fijar_nivel_por_id(user["id"], capacidad_id, body.nivel)
        if not ok:
            raise HTTPException(status_code=404, detail="Capacidad no encontrada")
        from .executors import antigravity_chat  # noqa: PLC0415
        await antigravity_chat.aplicar_perfil(user)
        return {"ok": True, "nivel": body.nivel}
    except perfil.PerfilInvalido as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@api_router.delete("/perfil/capacidades/{capacidad_id}")
async def borrar_capacidad(
    capacidad_id: int, user: dict = Depends(auth.current_user)
):
    ok = perfil.eliminar_capacidad(user["id"], capacidad_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Capacidad no encontrada")
    from .executors import antigravity_chat  # noqa: PLC0415
    await antigravity_chat.aplicar_perfil(user)
    return {"ok": True}


@api_router.delete("/perfil")
async def resetear_perfil(user: dict = Depends(auth.current_user)):
    perfil.borrar_perfil(user["id"])
    from .executors import antigravity_chat  # noqa: PLC0415
    await antigravity_chat.aplicar_perfil(user)
    return {"ok": True}


@api_router.post("/perfil/revision")
async def ejecutar_revision_perfil(user: dict = Depends(auth.current_user)):
    from . import perfil_observador  # noqa: PLC0415
    toca, desde = perfil_observador.debe_revisar(user["id"])
    if not toca:
        return {
            "apoyadas": [],
            "decaidas": [],
            "propuestas_retirada": [],
            "omitida": True,
        }
    senales = perfil_observador.leer_senales(user["id"], desde=desde)
    resultado = perfil_observador.revisar(user["id"], senales)
    perfil.marcar_revisado(user["id"])
    from .executors import antigravity_chat  # noqa: PLC0415
    await antigravity_chat.aplicar_perfil(user)
    resultado["omitida"] = False
    return resultado


@api_router.get("/perfil/entrevista/hipotesis")
async def obtener_hipotesis_entrevista(user: dict = Depends(auth.current_user)):
    from . import perfil_entrevista  # noqa: PLC0415
    mapa = {"carpetas": []}
    tiene_nodo = False
    connected_nodes = [
        n for n in db.list_nodes(user["id"]) if nodes.manager.is_online(n["id"])
    ]
    if connected_nodes:
        tiene_nodo = True
        try:
            res = await nodes.dispatch(
                user["id"],
                "inventario.mapa",
                {"raices": ["~"]},
                node_ref=connected_nodes[0]["id"],
                queue_if_offline=False,
            )
            if res.get("estado") == "completada" and isinstance(
                res.get("resultado"), dict
            ):
                mapa = res["resultado"]
            elif isinstance(res, dict) and "carpetas" in res:
                mapa = res
        except Exception as error:
            log.warning("No se pudo obtener inventario del nodo: %s", error)

    hipotesis = [
        {"clase": h.clase, "valor": h.valor, "evidencia": h.evidencia}
        for h in perfil_entrevista.hipotesis_de(mapa)
    ]
    return {"hipotesis": hipotesis, "tiene_nodo": tiene_nodo}


@api_router.post("/perfil/entrevista/propuesta")
async def generar_propuesta_entrevista(
    body: PropuestaRequest, user: dict = Depends(auth.current_user)
):
    from . import perfil_entrevista  # noqa: PLC0415
    pedidos = list(dict.fromkeys(body.terminos_pedidos))
    for termino in await perfil_entrevista.terminos_de_texto_ia(body.texto_libre):
        if termino not in pedidos:
            pedidos.append(termino)
    if not pedidos:
        pedidos = ["notes", "pdf"]
    # Sin respaldo genérico aquí: "search" a secas contra un registro público
    # grande no encuentra nada relacionado con la persona, solo ruido (Apple
    # Search Ads, Google Search Console, research de mercado...) — probado en
    # vivo el 27/08/2026. Mejor un bloque "encaja" vacío y honesto.
    adyacentes = list(dict.fromkeys(body.terminos_adyacentes))
    for termino in await perfil_entrevista.terminos_de_texto_ia(
        body.texto_libre_adyacente
    ):
        # Sin repetir lo ya pedido: un término que está en los dos sitios es
        # algo que la persona pidió, y ese bloque manda.
        if termino not in pedidos and termino not in adyacentes:
            adyacentes.append(termino)
    propuestas = perfil_entrevista.proponer(pedidos, adyacentes)
    perfil.registrar_propuestas(
        user["id"],
        [
            {
                "tipo": propuesta.tipo,
                "referencia": propuesta.referencia,
                "bloque": propuesta.bloque,
            }
            for propuesta in propuestas
        ],
    )
    # Nivel INFO a propósito: es lo único que queda de qué se le propuso a
    # quién, ni el texto libre ni la propia lista se guardan en ningún sitio.
    # Sin esto, auditar una entrevista real (como la primera prueba en vivo
    # del 27/08/2026) exige que la persona recuerde de memoria qué contestó.
    log.info(
        "Propuesta de entrevista para %s: pedidos=%s adyacentes=%s -> %s",
        user["id"],
        pedidos,
        adyacentes,
        [(p.bloque, p.referencia) for p in propuestas],
    )
    return [
        {
            "tipo": p.tipo,
            "referencia": p.referencia,
            "titulo": p.titulo,
            "justificacion": p.justificacion,
            "transporte": p.transporte,
            "bloque": p.bloque,
            "endpoint": p.endpoint,
            "paquete": p.paquete,
        }
        for p in propuestas
    ]


@api_router.post("/perfil/entrevista/turno")
async def turno_entrevista_endpoint(
    body: TurnoEntrevistaBody, user: dict = Depends(auth.current_user)
):
    from . import perfil_entrevista  # noqa: PLC0415
    historial = [{"rol": t.rol, "texto": t.texto} for t in body.historial]
    turno = await perfil_entrevista.turno_entrevista(historial)
    if turno.get("terminado"):
        # La conversación en sí no se guarda en ningún sitio (vive en el
        # estado de React del navegador): esto es lo único que queda de lo
        # que Vibi entendió al cerrarla.
        log.info(
            "Entrevista cerrada para %s: %s",
            user["id"],
            turno.get("resumen"),
        )
    return turno


@api_router.post("/perfil/entrevista/voz")
async def transcribir_entrevista(
    audio: UploadFile = File(...),
    user: dict = Depends(auth.current_user),
):
    """Solo transcribe: a diferencia de `/voz`, no enruta al motor general.

    La entrevista necesita lo que ha dicho la persona, no una respuesta de
    Vibi sobre ello — eso lo decide `turno_entrevista`, con su propio prompt
    acotado a los cuatro temas de esta especialización. Reutilizar `/voz`
    arrastraría el enrutamiento a herramientas y tareas, que aquí no pinta
    nada y además mezclaría la entrevista con el hilo de conversación real.
    """
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
            user["id"], audio.filename or "voz.webm", content
        )
    except Exception as error:
        log.warning("No se pudo transcribir el audio de la entrevista: %s", error)
        raise HTTPException(
            status_code=502,
            detail="No he podido transcribir el audio. Inténtalo de nuevo.",
        ) from error
    if not transcript:
        raise HTTPException(status_code=422, detail="No he detectado voz")
    return {"transcripcion": transcript}


@api_router.post("/perfil/entrevista/completar")
async def completar_entrevista(
    body: CompletarEntrevistaBody, user: dict = Depends(auth.current_user)
):
    user_id = user["id"]
    descartes = perfil.guardar_entrevista(
        user_id,
        [afirmacion.model_dump() for afirmacion in body.afirmaciones],
        [capacidad.model_dump() for capacidad in body.capacidades],
    )
    if descartes:
        # Lo apartado se cuenta, no se esconde: casi siempre es una propuesta
        # nuestra que llegó incompleta, y sin este rastro el usuario ve
        # desaparecer algo que había marcado sin saber por qué.
        log.warning(
            "Entrevista aplicada para %s con %d descarte(s): %s",
            user_id,
            len(descartes),
            [(d["referencia"], d["motivo"]) for d in descartes],
        )
    from .executors import antigravity_chat  # noqa: PLC0415
    await antigravity_chat.aplicar_perfil(user)

    return {**obtener_perfil(user), "descartes": descartes}

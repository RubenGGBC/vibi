"""Procesamiento de mensajes independiente del canal de entrada."""
from dataclasses import dataclass
from typing import Literal

from .. import ai_providers, db, router, tasks, tools
from ..claude_models import ClaudeModel
from ..config import settings
from ..executors import groq_chat

ORIGEN_POR_CANAL = {
    "pwa": "pwa",
    "telegram": "telegram",
    "cara": "cara",
}


@dataclass(frozen=True)
class ResultadoMensaje:
    via: Literal["rapida", "agentica", "herramienta"]
    respuesta: str | None = None
    task: dict | None = None
    resolucion: tasks.ResolucionProyecto | None = None
    artifacts: tuple[dict, ...] = ()


async def procesar_encargo(
    user: dict,
    prompt: str,
    proyecto: str | None,
    canal: str,
    modelo: ClaudeModel | None = None,
) -> ResultadoMensaje:
    resolucion = tasks.resolver_proyecto(user["id"], proyecto)
    if resolucion.estado != "ok":
        return ResultadoMensaje("agentica", resolucion=resolucion)

    agent_model = modelo or ai_providers.get_settings(user["id"]).agent_model
    task = await tasks.encolar_tarea(
        user["id"], user["nombre"], prompt, resolucion.workspace, agent_model
    )
    db.log_event(
        "proyecto_seleccionado",
        user["id"],
        task_id=task["id"],
        proyecto=proyecto,
        canal=canal,
    )
    return ResultadoMensaje("agentica", task=task, resolucion=resolucion)


async def procesar_mensaje(
    user: dict,
    texto: str,
    canal: str,
    modelo: ClaudeModel | None = None,
    client_ref: str | None = None,
) -> ResultadoMensaje:
    conversation = db.get_active_conversation(user["id"])
    history = (
        db.list_context_messages(
            conversation["id"], settings.groq_recent_context_tokens
        )
        if conversation
        else []
    )
    clasificacion = await router.clasificar(texto, history, user_id=user["id"])
    via = clasificacion["via"]
    proyecto = clasificacion["proyecto"]
    db.log_event(
        "mensaje", user["id"], via=via, proyecto=proyecto, canal=canal
    )

    if via == "rapida":
        origen = ORIGEN_POR_CANAL.get(canal)
        if not origen:
            raise ValueError(f"Canal de conversación no soportado: {canal}")
        respuesta = await groq_chat.responder(
            user["id"], user["nombre"], texto, origen, client_ref
        )
        return ResultadoMensaje("rapida", respuesta=respuesta)

    if via == "herramienta":
        origen = ORIGEN_POR_CANAL.get(canal)
        if not origen:
            raise ValueError(f"Canal de conversación no soportado: {canal}")
        execution = await tools.execute(
            clasificacion.get("herramienta") or "",
            user,
            clasificacion.get("argumentos") or {},
        )
        artifacts = tuple(execution["result"].get("files", []))
        content = str(execution["result"].get("content") or "").strip()
        if content and artifacts:
            response = await groq_chat.responder(
                user["id"],
                user["nombre"],
                texto,
                origen,
                client_ref,
                document_context=(artifacts[0]["name"], content),
                purpose="tools",
            )
            return ResultadoMensaje(
                "herramienta", respuesta=response, artifacts=artifacts
            )
        if artifacts and clasificacion.get("herramienta") == "files.read":
            response = (
                f"He encontrado {artifacts[0]['name']}, pero no puedo extraer "
                "texto de ese formato. Puedes descargarlo para abrirlo."
            )
        elif artifacts:
            names = ", ".join(file["name"] for file in artifacts[:5])
            suffix = "" if len(artifacts) <= 5 else f" y {len(artifacts) - 5} más"
            response = f"He encontrado {len(artifacts)} archivo(s): {names}{suffix}."
        else:
            response = "No he encontrado archivos que coincidan con esa búsqueda."
        conversation = conversation or db.get_or_create_active_conversation(user["id"])
        db.add_conversation_message(
            conversation["id"], "user", texto, origen, client_ref
        )
        db.add_conversation_message(
            conversation["id"], "assistant", response, origen
        )
        return ResultadoMensaje(
            "herramienta", respuesta=response, artifacts=artifacts
        )

    agent_model = modelo or ai_providers.get_settings(user["id"]).agent_model
    return await procesar_encargo(user, texto, proyecto, canal, agent_model)

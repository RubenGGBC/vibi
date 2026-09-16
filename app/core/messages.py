"""Procesamiento de mensajes independiente del canal de entrada."""
from dataclasses import dataclass
from typing import Literal

from .. import ai_providers, db, events, skills, tasks
from ..claude_models import ClaudeModel
from ..executors import chat

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
    tool_ids: tuple[str, ...] = (),
    conversation_id: str | None = None,
    file_ids: tuple[str, ...] = (),
) -> ResultadoMensaje:
    command = skills.parse_command(texto)
    if command:
        slug, request = command
        skill = skills.get_active_by_slug(user, slug)
        if not skill:
            response = f"No hay ninguna skill activa con el identificador {slug}."
            run_result = {"response": response, "artifacts": []}
        elif not request:
            response = f"Escribe una petición después de /skill {slug}."
            run_result = {"response": response, "artifacts": []}
        else:
            run_result = await skills.run_skill(user, skill["id"], request)
            response = run_result["response"]

        origin = ORIGEN_POR_CANAL.get(canal)
        if not origin:
            raise ValueError(f"Canal de conversación no soportado: {canal}")
        conversation = db.get_or_create_active_conversation(user["id"])
        if conversation_id and conversation["id"] != conversation_id:
            raise chat.ConversationChanged
        user_message = db.add_conversation_message(
            conversation["id"], "user", texto, origin, client_ref
        )
        await events.mensaje_chat(user["id"], user_message)
        assistant_message = db.add_conversation_message(
            conversation["id"], "assistant", response, origin
        )
        await events.mensaje_chat(user["id"], assistant_message)
        # La ejecución externa de una skill no forma parte del transcript nativo
        # de Claude. Fuerza un arranque que reconstruya el historial en el próximo turno.
        await chat.close_session(conversation["id"])
        db.update_conversation_session(conversation["id"], user["id"], None)
        db.log_event(
            "mensaje", user["id"], via="herramienta", proyecto=None, canal=canal
        )
        return ResultadoMensaje(
            "herramienta",
            respuesta=response,
            artifacts=tuple(run_result.get("artifacts", [])),
        )

    origin = ORIGEN_POR_CANAL.get(canal)
    if not origin:
        raise ValueError(f"Canal de conversación no soportado: {canal}")
    result = await chat.respond(
        user,
        texto,
        origin,
        client_ref,
        attached_tool_ids=tool_ids,
        # La cara locuta la respuesta: pide redacción hablada y búsquedas cortas.
        voz=canal == "cara",
        conversation_id=conversation_id,
        attached_file_ids=file_ids,
    )
    via = "herramienta" if result.artifacts else "rapida"
    db.log_event(
        "mensaje", user["id"], via="claude_code", proyecto=None, canal=canal
    )
    return ResultadoMensaje(
        via,
        respuesta=result.response,
        artifacts=result.artifacts,
    )

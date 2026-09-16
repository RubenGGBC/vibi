"""Procesamiento de mensajes independiente del canal de entrada."""
from dataclasses import dataclass
from typing import Literal

from .. import ai_providers, db, events, skills, tasks
from ..executors import agy_modelos, antigravity_chat
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


async def _responder_como_comando(
    user: dict,
    texto: str,
    canal: str,
    response: str,
    client_ref: str | None,
    conversation_id: str | None,
    artifacts: tuple[dict, ...] = (),
) -> ResultadoMensaje:
    """Deja un comando —`/skill`, `/model`— escrito en el hilo como un turno
    más, sin pasar por el motor de chat.

    Comparten esto porque los dos necesitan lo mismo: que la orden y la
    respuesta queden en el historial igual que cualquier mensaje, y que la
    sesión se reconstruya después —`close_session`—, porque lo que acaba de
    pasar no formaba parte del transcript nativo del motor.
    """
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
    await chat.close_session(conversation["id"])
    db.update_conversation_session(conversation["id"], user["id"], None)
    db.log_event("mensaje", user["id"], via="herramienta", proyecto=None, canal=canal)
    return ResultadoMensaje("herramienta", respuesta=response, artifacts=artifacts)


def _etiqueta_de_effort(effort: str) -> str:
    return {"low": "bajo", "medium": "medio", "high": "alto"}.get(effort, effort)


async def _procesar_comando_model(
    user: dict, texto: str, canal: str, client_ref: str | None, conversation_id: str | None
) -> ResultadoMensaje:
    """Elegir y cambiar el modelo de agy y su effort, escrito en el hilo.

    Se aplica al momento: guardar la elección no basta, porque `agy` es un
    solo proceso por usuario que lee el modelo al arrancar. `aplicar_perfil`
    lo mata para que el turno siguiente lo relance ya con el nuevo.
    """
    try:
        modelos = agy_modelos.listar()
    except agy_modelos.ErrorModelos as error:
        return await _responder_como_comando(
            user, texto, canal, str(error), client_ref, conversation_id
        )

    peticion = agy_modelos.interpretar(texto, modelos)
    if peticion.tipo == "listar":
        lineas = [f"{m.id}\t{m.etiqueta}" for m in modelos]
        response = "Modelos de agy disponibles:\n" + "\n".join(lineas)
        return await _responder_como_comando(
            user, texto, canal, response, client_ref, conversation_id
        )
    if peticion.tipo == "error":
        return await _responder_como_comando(
            user, texto, canal, peticion.error, client_ref, conversation_id
        )

    configured = ai_providers.get_settings(user["id"])
    if peticion.tipo == "por_defecto":
        nuevo = ai_providers.AISettings(
            **{**configured.__dict__, "chat_model": "", "antigravity_effort": ""}
        )
        response = "Agy vuelve al modelo que tenga configurado el servidor."
    else:
        nuevo = ai_providers.AISettings(
            **{
                **configured.__dict__,
                "chat_provider": "antigravity",
                "chat_model": peticion.modelo.id,
                "antigravity_effort": peticion.effort or "",
            }
        )
        response = f"Agy pasa a usar {peticion.modelo.etiqueta}."
        if peticion.effort:
            response += f" Effort: {_etiqueta_de_effort(peticion.effort)}."
    ai_providers.save_settings(user["id"], nuevo)
    await antigravity_chat.aplicar_perfil(user)
    return await _responder_como_comando(
        user, texto, canal, response, client_ref, conversation_id
    )


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
    if agy_modelos.es_comando(texto):
        return await _procesar_comando_model(
            user, texto, canal, client_ref, conversation_id
        )

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

        return await _responder_como_comando(
            user,
            texto,
            canal,
            response,
            client_ref,
            conversation_id,
            tuple(run_result.get("artifacts", [])),
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

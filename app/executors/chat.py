"""El director del chat: qué motor contesta y qué es común a todos.

Morgana puede conversar con dos motores distintos:

  - `claude`: Claude Code vía Agent SDK. Trae las tools internas de Morgana
    (archivos, tareas, actividad) y es el que responde por defecto.
  - `antigravity`: Gemini a través de la CLI `agy` del usuario, que mantiene
    viva en un ConPTY. Va más rápido y no gasta API de Anthropic, pero sus
    herramientas son las que le expone Morgana por MCP.

Lo que NO depende del motor vive aquí: resolver la conversación activa, el
candado por conversación, persistir los mensajes y emitir los eventos de la
UI. Los motores solo se ocupan de producir la respuesta a un turno.
"""
from __future__ import annotations

import asyncio
import logging

from .. import ai_providers, db, events
from .chat_engine import ChatEngine, ChatResult, ConversationChanged

log = logging.getLogger("morgana.chat")


def _engines() -> dict[str, ChatEngine]:
    # Import perezoso: cargar los motores arriba crea un ciclo con los
    # módulos que a su vez importan este director.
    from . import antigravity_chat, claude_chat

    return {"anthropic": claude_chat.ENGINE, "antigravity": antigravity_chat.ENGINE}


def engine_for(user_id: str) -> ChatEngine:
    """El motor elegido en Ajustes, con Claude como red de seguridad."""
    engines = _engines()
    provider = ai_providers.get_settings(user_id).chat_provider
    engine = engines.get(provider)
    if engine is None:
        log.warning("chat_provider desconocido (%s); uso Claude", provider)
        return engines["anthropic"]
    return engine


# Las tareas de precalentado se guardan para que el recolector no se las lleve
# a media faena: `create_task` solo mantiene una referencia débil.
_precalentando: set = set()


def precalentar_en_segundo_plano(user: dict, conversation: dict) -> None:
    """Pide al motor que prepare la sesión sin hacer esperar a quien llama.

    Se usa al abrir una conversación de voz: quien invoca a Morgana todavía
    tiene que decir su frase y esperar a que se transcriba, así que el motor
    puede ir montándose mientras, en vez de empezar cuando ya hay alguien
    esperando la respuesta.
    """
    engine = engine_for(user["id"])
    preparar = getattr(engine, "warm_session", None)
    if preparar is None:
        return  # El motor no necesita preparación previa.

    async def _preparar() -> None:
        try:
            await preparar(user, conversation)
        except Exception:
            # Que no salga bien no rompe nada: el turno la abrirá al llegar.
            log.warning("No se pudo precalentar %s", engine.name, exc_info=True)

    tarea = asyncio.create_task(_preparar())
    _precalentando.add(tarea)
    tarea.add_done_callback(_precalentando.discard)


async def close_session(conversation_id: str) -> None:
    """Cierra la sesión de la conversación en todos los motores.

    Se llama al archivar o reiniciar una conversación, y el usuario puede
    haber cambiado de motor por el camino: cerrar solo el actual dejaría
    procesos vivos con contexto viejo.
    """
    for engine in _engines().values():
        try:
            await engine.close_session(conversation_id)
        except Exception:
            log.exception("No se pudo cerrar la sesión en %s", engine.name)


async def close_all_sessions() -> None:
    for engine in _engines().values():
        try:
            await engine.close_all_sessions()
        except Exception:
            log.exception("No se pudieron cerrar las sesiones de %s", engine.name)


async def respond(
    user: dict,
    text: str,
    origin: str,
    client_ref: str | None = None,
    attached_tool_ids: tuple[str, ...] = (),
    voz: bool = False,
    conversation_id: str | None = None,
) -> ChatResult:
    """Añade el turno a la conversación y lo ejecuta en el motor elegido."""
    conversation = db.get_or_create_active_conversation(user["id"])
    if conversation_id and conversation["id"] != conversation_id:
        raise ConversationChanged

    engine = engine_for(user["id"])
    async with engine.conversation_lock(conversation["id"]):
        # Refresca el estado: Thinking o la sesión pudieron cambiar en otro dispositivo.
        active = db.get_active_conversation(user["id"])
        if conversation_id and (not active or active["id"] != conversation_id):
            raise ConversationChanged
        conversation = active or conversation
        bootstrap_history = (
            tuple(db.list_context_messages(conversation["id"], 12_000))
            if engine.needs_history(conversation)
            else ()
        )
        user_message = db.add_conversation_message(
            conversation["id"], "user", text, origin, client_ref
        )
        await events.mensaje_chat(user["id"], user_message)
        turn_id = client_ref or f"message-{user_message['id']}"
        await events.inicio_respuesta_chat(user["id"], conversation["id"], turn_id)
        try:
            result = await _run_with_fallback(
                engine,
                user,
                conversation,
                text,
                attached_tool_ids,
                turn_id,
                bootstrap_history,
                voz,
                origin,
            )
            assistant_message = db.add_conversation_message(
                conversation["id"], "assistant", result.response, origin
            )
            await events.mensaje_chat(user["id"], assistant_message)
            return result
        finally:
            await events.fin_respuesta_chat(user["id"], conversation["id"], turn_id)


async def _run_with_fallback(
    engine: ChatEngine,
    user: dict,
    conversation: dict,
    text: str,
    attached_tool_ids: tuple[str, ...],
    turn_id: str,
    bootstrap_history: tuple[dict, ...],
    voz: bool,
    canal: str = "pwa",
) -> ChatResult:
    """Si el motor elegido se cae, contesta Claude en lugar de dejar al usuario sin nada.

    Antigravity depende de un proceso externo (`agy`) que puede no estar
    instalado, no estar autenticado o morirse a media conversación. Un chat
    personal no puede quedarse mudo por eso.
    """
    try:
        return await engine.run_turn(
            user,
            conversation,
            text,
            attached_tool_ids,
            turn_id,
            bootstrap_history,
            voz,
            canal,
        )
    except ConversationChanged:
        raise
    except Exception as error:
        respaldo = _engines()["anthropic"]
        if engine is respaldo:
            raise
        log.exception("El motor %s falló; recurro a Claude", engine.name)
        # Abandonar y no cerrar: cerrar conserva a propósito lo que el motor
        # tenga montado, y montado es justo como se quedaba el `agy` colgado
        # que hacía fallar también todos los turnos siguientes.
        await engine.abandon_session(user, conversation["id"], str(error))
        db.log_event(
            "motor_caido",
            user["id"],
            motor=engine.name,
            motivo=str(error)[:300],
        )
        # El motor caído no dejó nada en la conversación de Claude: hay que
        # reconstruirle el historial aunque el motor anterior no lo pidiera.
        historial = bootstrap_history or tuple(
            db.list_context_messages(conversation["id"], 12_000)
        )
        result = await respaldo.run_turn(
            user,
            conversation,
            text,
            attached_tool_ids,
            turn_id,
            historial,
            voz,
            canal,
        )
        # Que vuelva solo. Levantarlo cuesta segundos, pero aquí ya no hay
        # nadie esperándolo: el turno lo está contestando Claude. Sin esto el
        # usuario se quedaba en el respaldo hasta reiniciar el servidor.
        precalentar_en_segundo_plano(user, conversation)
        if voz:
            # Esto se locuta entero. Leerle el error en voz alta, corchetes
            # incluidos, no le sirve de nada a quien está escuchando; queda
            # registrado en Actividad, que es donde se mira.
            return result
        aviso = f"[{engine.display_name} no estaba disponible: {error}. Responde Claude.]"
        return ChatResult(
            response=f"{result.response}\n\n{aviso}",
            artifacts=result.artifacts,
        )

"""Vía rápida con Gemini: la CLI `agy` viva, pero escuchada por su propia API.

`agy` no es un programa monolítico: levanta dentro de sí un language server y
la interfaz de terminal es solo un cliente suyo. Morgana usa ese mismo
servidor, así que la respuesta llega como JSON con streaming y con un estado
explícito de «terminado», en vez de sacarse a pulso del SQLite interno
mientras se adivina el fin de turno por el silencio en pantalla.

El pseudoterminal sigue ahí, pero solo para dos cosas: mantener el proceso en
pie —el servidor muere con él— y teclear el turno. Teclear no es pereza:
mandarlo por `SendUserCascadeMessage` cuesta dos segundos fijos, medidos, y el
PTY hace falta igualmente.

Esto depende de que el usuario tenga `agy` instalado y con la sesión iniciada.
Cuando no lo esté, el motor falla y `chat.py` pasa el turno a Claude.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field

from .. import events, tasks
from ..config import settings
from . import agy_client, agy_process
from .agy_process import AgyUnavailable
from .chat_engine import ChatResult
from .claude_chat import LOCUCION, PERSONALIDAD

log = logging.getLogger("morgana.antigravity")

# Lo que se espera a que la conversación aparezca tras teclear el primer turno.
CONVERSATION_TIMEOUT = 30.0
TURN_TIMEOUT = 300.0


@dataclass
class _LiveSession:
    conversation_id: str
    process: object          # agy_process.AgyProcess
    client: object           # agy_client.AgyClient
    cascade_id: str | None = None
    user_id: str = ""
    last_used_at: float = field(default_factory=time.time)
    # Lo último que dijo, para no confundirlo con lo que va a decir ahora.
    last_response: str = ""


# El proceso de `agy` es del usuario, no de la conversación. Atarlo a la
# conversación salía carísimo: el canal de voz la reinicia cada vez que
# invocas a Morgana, y eso mataba el proceso, con lo que el turno siguiente
# pagaba el arranque entero (13-42 s medidos en uso real). La CLI sabe empezar
# conversación nueva sola con `/new`, en un segundo.
_processes: dict[str, object] = {}
_process_touch: dict[str, float] = {}
_sessions: dict[str, _LiveSession] = {}
_sessions_lock = asyncio.Lock()
_conversation_locks: dict[str, asyncio.Lock] = {}


def _conversation_lock(conversation_id: str) -> asyncio.Lock:
    lock = _conversation_locks.get(conversation_id)
    if lock is None:
        lock = asyncio.Lock()
        _conversation_locks[conversation_id] = lock
    return lock


async def _consume_turn(
    session: _LiveSession,
    user: dict,
    conversation_id: str,
    turn_id: str | None,
    enviar=None,
) -> str:
    """Sigue el turno por el stream y va soltando lo que el modelo escribe.

    El stream reenvía la respuesta entera cada vez que crece, así que a la cara
    solo se le pasa la parte nueva; si no, locutaría lo mismo una y otra vez.
    """
    if turn_id:
        # Abre el turno en el canal de la cara: sin esto la locución
        # arrastraría el texto del turno anterior.
        await events.fragmento_chat(
            user["id"], conversation_id, turn_id, "", reset=True
        )

    turno = agy_client.TurnText()
    cola: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    escuchando = threading.Event()

    def producir() -> None:
        # El stream es bloqueante, así que se lee en un hilo y se va pasando.
        try:
            updates = session.client.stream_updates(
                session.cascade_id, skip_text=session.last_response
            )
        except Exception as error:  # noqa: BLE001
            loop.call_soon_threadsafe(cola.put_nowait, error)
            escuchando.set()
            loop.call_soon_threadsafe(cola.put_nowait, None)
            return
        escuchando.set()
        try:
            for update in updates:
                loop.call_soon_threadsafe(cola.put_nowait, update)
        except Exception as error:  # noqa: BLE001
            loop.call_soon_threadsafe(cola.put_nowait, error)
        finally:
            loop.call_soon_threadsafe(cola.put_nowait, None)

    threading.Thread(target=producir, daemon=True).start()

    if enviar is not None:
        # El turno no entra hasta que el stream está escuchando: al revés se
        # pierde la respuesta y solo llega el eco de la anterior.
        await asyncio.to_thread(escuchando.wait, 30.0)
        await enviar()

    deadline = time.time() + TURN_TIMEOUT
    while True:
        restante = deadline - time.time()
        if restante <= 0:
            raise AgyUnavailable("agy no cerró el turno a tiempo")
        try:
            item = await asyncio.wait_for(cola.get(), timeout=restante)
        except asyncio.TimeoutError:
            raise AgyUnavailable("agy no cerró el turno a tiempo") from None
        if item is None:
            break
        if isinstance(item, Exception):
            raise item

        nuevo = turno.advance(item.text or "")
        if nuevo and turn_id:
            # Cada trozo cierra frase lo bastante como para locutarlo ya, sin
            # esperar al resto del turno.
            await events.fragmento_chat(
                user["id"], conversation_id, turn_id, nuevo, boundary=True
            )
        if item.done:
            break

    session.last_response = turno.full.strip()
    return session.last_response


async def _process_for(user: dict, workspace) -> tuple[object, set[str]]:
    """El proceso de `agy` del usuario, arrancándolo solo si hace falta.

    Si ya había uno, se le pide una conversación limpia con `/new` en vez de
    reiniciarlo: cuesta un segundo en lugar de la decena larga que cuesta
    levantar la CLI desde cero.
    """
    process = _processes.get(user["id"])
    if process is not None and process.alive():
        # Las que ya había: la nueva se reconoce después por no estar aquí.
        try:
            conocidas = set(
                await asyncio.to_thread(agy_client.AgyClient(process.port).conversations)
            )
        except agy_client.AgyError:
            conocidas = set()
        await asyncio.to_thread(process.type, "/new")
        return process, conocidas

    if process is not None:
        _processes.pop(user["id"], None)
    process = await asyncio.to_thread(
        agy_process.AgyProcess.start,
        settings.agy_binary,
        str(workspace),
        settings.antigravity_model,
    )
    _processes[user["id"]] = process
    return process, set()


async def _start_session(conversation_id: str, workspace, user: dict,
                         bootstrap_history: tuple[dict, ...]) -> _LiveSession:
    process, conocidas = await _process_for(user, workspace)
    session = _LiveSession(
        conversation_id=conversation_id,
        process=process,
        client=agy_client.AgyClient(process.port),
        user_id=user["id"],
    )

    # La CLI arranca sin saber quién es ni con quién habla. El primer turno
    # sirve para presentarla y, de paso, para que se cree la conversación.
    presentacion = PERSONALIDAD.format(nombre=user["nombre"])
    if bootstrap_history:
        historial = "\n".join(
            f"{message['role']}: {message['content']}" for message in bootstrap_history
        )
        presentacion += (
            "\n\n<historial_previo>\nEsta conversación venía de antes:\n"
            f"{historial}\n</historial_previo>"
        )
    presentacion += "\n\nResponde solo: preparada."

    async def teclear_presentacion() -> None:
        await asyncio.to_thread(process.type, presentacion)

    await teclear_presentacion()
    session.cascade_id = await _wait_for_conversation(
        session, reintentar=teclear_presentacion, conocidas=conocidas
    )
    await _consume_turn(session, user, conversation_id, turn_id=None)
    log.info("Sesión Antigravity lista para %s", conversation_id)
    return session


async def _wait_for_conversation(
    session: _LiveSession,
    reintentar=None,
    timeout: float = CONVERSATION_TIMEOUT,
    conocidas: set[str] | None = None,
) -> str:
    """Espera a que `agy` registre la conversación que acaba de empezar.

    Si no aparece a media espera, se vuelve a teclear una vez: la CLI se come
    lo que se le escriba mientras aún está inicializando, y cuánto tarda en
    estar lista varía de un arranque a otro.
    """
    deadline = time.time() + timeout
    reintentado = False
    while time.time() < deadline:
        try:
            abiertas = await asyncio.to_thread(session.client.conversations)
        except agy_client.AgyError:
            abiertas = []
        # Tras un `/new` conviven la vieja y la nueva: hay que coger la que no
        # estaba, o Morgana seguiría leyendo el hilo que se acaba de cerrar.
        nuevas = [c for c in abiertas if c not in (conocidas or set())]
        if nuevas:
            return nuevas[0]
        if (
            reintentar is not None
            and not reintentado
            and time.time() > deadline - timeout / 2
        ):
            reintentado = True
            log.warning("agy no registró la conversación; tecleo otra vez")
            await reintentar()
        await asyncio.sleep(0.3)
    await asyncio.to_thread(session.process.kill)
    raise AgyUnavailable("agy no llegó a abrir la conversación")


async def _prune(exclude_user: str) -> None:
    """Cierra los `agy` que lleven mucho sin usarse y respeta el tope.

    Se razona por proceso y no por conversación: un usuario abre y cierra
    conversaciones constantemente —el canal de voz lo hace en cada
    invocación— y el proceso tiene que sobrevivir a todas ellas.
    """
    ahora = time.time()
    async with _sessions_lock:
        caducados = [
            user_id
            for user_id, visto in _process_touch.items()
            if user_id != exclude_user
            and ahora - visto > settings.antigravity_idle_seconds
        ]
        sobrantes = sorted(
            (visto, user_id)
            for user_id, visto in _process_touch.items()
            if user_id != exclude_user and user_id not in caducados
        )
        while (
            len(_processes) - len(caducados) >= settings.antigravity_max_sessions
            and sobrantes
        ):
            caducados.append(sobrantes.pop(0)[1])

        cerrar = []
        for user_id in caducados:
            process = _processes.pop(user_id, None)
            _process_touch.pop(user_id, None)
            if process is not None:
                cerrar.append(process)
            for conversation_id, session in list(_sessions.items()):
                if session.user_id == user_id:
                    _sessions.pop(conversation_id, None)
    for process in cerrar:
        await asyncio.to_thread(process.kill)


async def _get_session(
    user: dict, conversation_id: str, bootstrap_history: tuple[dict, ...]
) -> _LiveSession:
    async with _sessions_lock:
        session = _sessions.get(conversation_id)
    if session is not None:
        if session.process.alive():
            session.last_used_at = time.time()
            _process_touch[user["id"]] = time.time()
            return session
        log.warning("La sesión agy de %s se había muerto; la reabro", conversation_id)
        async with _sessions_lock:
            _sessions.pop(conversation_id, None)

    await _prune(exclude_user=user["id"])
    workspace = tasks.directorio_usuario(user["id"])
    session = await _start_session(
        conversation_id, workspace, user, bootstrap_history
    )
    async with _sessions_lock:
        _sessions[conversation_id] = session
        _process_touch[user["id"]] = time.time()
    return session


async def close_session(conversation_id: str) -> None:
    """Olvida la conversación, pero deja a `agy` en pie.

    Matarlo aquí es lo que hacía que hablar por voz costara medio minuto: cada
    invocación reinicia la conversación, y el proceso se llevaba por delante
    la sesión entera. Se reaprovecha en la siguiente con `/new`.
    """
    async with _sessions_lock:
        _sessions.pop(conversation_id, None)


async def close_all_sessions() -> None:
    """Apagado del servidor: aquí sí se cierran los procesos."""
    async with _sessions_lock:
        procesos = list(_processes.values())
        _processes.clear()
        _process_touch.clear()
        _sessions.clear()
    for process in procesos:
        await asyncio.to_thread(process.kill)


async def warm_up(user_id: str, nombre: str) -> None:
    """Deja una sesión lista antes de que el usuario escriba.

    Abrir `agy` cuesta unos segundos. Pagarlos al arrancar el servidor, cuando
    no hay nadie esperando, hace que el primer mensaje ya salga rápido.
    """
    from .. import db  # noqa: PLC0415

    try:
        conversation = db.get_or_create_active_conversation(user_id)
        async with _conversation_lock(conversation["id"]):
            await _get_session({"id": user_id, "nombre": nombre}, conversation["id"], ())
    except Exception as error:
        log.warning("No se pudo precalentar Antigravity: %s", error)


class _AntigravityEngine:
    name = "antigravity"
    display_name = "Antigravity"

    def conversation_lock(self, conversation_id: str) -> asyncio.Lock:
        return _conversation_lock(conversation_id)

    def needs_history(self, conversation: dict) -> bool:
        # El contexto vive en el proceso: solo hace falta si hay que reabrirlo.
        return conversation["id"] not in _sessions

    async def run_turn(
        self,
        user: dict,
        conversation: dict,
        text: str,
        attached_tool_ids: tuple[str, ...],
        turn_id: str,
        bootstrap_history: tuple[dict, ...],
        voz: bool,
    ) -> ChatResult:
        session = await _get_session(user, conversation["id"], bootstrap_history)
        session.last_used_at = time.time()
        turno = f"{text}\n\n{LOCUCION}" if voz else text

        async def enviar() -> None:
            await asyncio.to_thread(session.process.type, turno)

        respuesta = await _consume_turn(
            session, user, conversation["id"], turn_id, enviar=enviar
        )
        if not respuesta:
            raise AgyUnavailable("agy no devolvió respuesta en este turno")
        return ChatResult(response=respuesta)

    async def close_session(self, conversation_id: str) -> None:
        await close_session(conversation_id)

    async def close_all_sessions(self) -> None:
        await close_all_sessions()


ENGINE = _AntigravityEngine()

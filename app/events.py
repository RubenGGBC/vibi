"""WebSocket autenticado y difusión de eventos por usuario."""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth, db
from .serializers import serializar_archivo, serializar_mensaje, serializar_tarea

log = logging.getLogger("vibi.events")


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[str, dict[str, set[WebSocket]]] = {}
        self._send_locks: dict[str, asyncio.Lock] = {}

    async def connect(
        self,
        user_id: str,
        device_id: str,
        websocket: WebSocket,
        *,
        accept: bool = True,
    ) -> None:
        if accept:
            await websocket.accept()
        devices = self.connections.setdefault(user_id, {})
        devices.setdefault(device_id, set()).add(websocket)

    def disconnect(
        self, user_id: str, device_id: str, websocket: WebSocket
    ) -> None:
        devices = self.connections.get(user_id)
        if not devices:
            return
        sockets = devices.get(device_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            devices.pop(device_id, None)
        if not devices:
            self.connections.pop(user_id, None)

    async def _send_unlocked(self, user_id: str, payload: dict) -> None:
        devices = self.connections.get(user_id, {})
        targets = [
            (device_id, websocket)
            for device_id, sockets in tuple(devices.items())
            for websocket in tuple(sockets)
        ]
        for device_id, websocket in targets:
            try:
                await websocket.send_json(payload)
            except Exception:  # noqa: BLE001
                self.disconnect(user_id, device_id, websocket)

    async def send(self, user_id: str, payload: dict) -> None:
        lock = self._send_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            await self._send_unlocked(user_id, payload)

    async def send_active_message(self, user_id: str, message: dict) -> None:
        """Ordena mensajes y resets, y descarta respuestas ya archivadas."""
        lock = self._send_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            active = db.get_active_conversation(user_id)
            if not active or active["id"] != message["conversation_id"]:
                return
            await self._send_unlocked(
                user_id,
                {"tipo": "chat_message", "message": serializar_mensaje(message)},
            )


manager = ConnectionManager()
router = APIRouter()


async def notificar(
    user_id: str,
    texto: str,
    task_id: str | None = None,
    acciones: bool = False,
) -> None:
    payload = {"tipo": "notificacion", "texto": texto}
    if task_id:
        payload["task_id"] = task_id
    await manager.send(user_id, payload)


async def vigilancia_cambiada(
    user_id: str, activa: bool, que_espero: str = ""
) -> None:
    """De qué está pendiente Vibi ahora mismo, para que la cara lo enseñe.

    Es estado y no aviso, y por eso va aparte de `notificar`: no hay que
    decirlo en voz alta ni apuntarlo en ningún sitio. Se manda entero —activa y
    de qué— en vez de un «empieza»/«termina», porque una ventana que acabe de
    abrirse tiene que poder ponerse al día con un solo mensaje.
    """
    await manager.send(
        user_id,
        {"tipo": "vigilancia", "activa": activa, "que_espero": que_espero},
    )


async def notificar_hablando(user_id: str, texto: str) -> None:
    """Un aviso que además hay que decir en voz alta.

    Va por el mismo canal que `notificar` pero marcado, porque no todo lo que
    llega por ahí debe sonar: una tarea terminada o un archivo recibido se leen
    en pantalla y ya. Lo que sí se dice son las notificaciones del sistema, que
    es de lo que va el marcador.
    """
    await manager.send(
        user_id, {"tipo": "notificacion", "texto": texto, "hablar": True}
    )


async def tarea_actualizada(user_id: str, task: dict) -> None:
    await manager.send(
        user_id,
        {"tipo": "tarea_actualizada", "task": serializar_tarea(task)},
    )


async def mensaje_chat(user_id: str, message: dict) -> None:
    await manager.send_active_message(user_id, message)


async def inicio_respuesta_chat(
    user_id: str, conversation_id: str, turn_id: str
) -> None:
    await manager.send(
        user_id,
        {
            "tipo": "chat_runtime",
            "event": "started",
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "label": "Conectando con Claude Code…",
        },
    )


async def progreso_chat(
    user_id: str,
    conversation_id: str,
    turn_id: str,
    label: str,
    herramienta: str = "",
) -> None:
    """Cuenta en qué anda el turno.

    `label` es la frase para leer («Ejecutando en el terminal…») y `herramienta`
    la clave estable de qué se está usando. Van separadas a propósito: la frase
    está en español y se reescribe cuando suena mejor de otra forma, mientras que
    de la clave cuelga la cara que pone Vibi, y una cara que cambia porque
    alguien ha retocado un texto sería un error muy difícil de ver.

    La clave se manda cruda, tal como la nombra cada motor —`Bash`, `SEARCH_WEB`,
    `mcp__playwright__browser_click`—, y es el frontend quien la clasifica. No se
    normaliza aquí porque no hay lista cerrada: `agy` estrena tipos de paso sin
    avisar, y un diccionario en el servidor solo conseguiría que lo que no
    conoce llegue como vacío en vez de llegar como lo que es.
    """
    await manager.send(
        user_id,
        {
            "tipo": "chat_runtime",
            "event": "progress",
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "label": label[:160],
            "herramienta": herramienta[:120],
        },
    )


async def paso_del_motor(
    user_id: str,
    conversation_id: str,
    turn_id: str,
    tipo: str,
    estado: str,
    detalle: str = "",
) -> None:
    """Un paso concreto de lo que el motor está haciendo, con su detalle.

    Distinto de `progreso_chat`, que existe para la cara: aquel manda una frase
    y una clave, lo justo para poner el gesto que toca. Esto manda el comando
    literal, la consulta buscada o la herramienta llamada, que es lo que hace
    falta para mirar por encima del hombro y entender por qué Vibi ha tardado un
    minuto o por qué ha contestado lo que ha contestado.

    Se emite por cada cambio de estado de cada paso, no solo al empezar: ver que
    algo lleva veinte segundos «en curso» es la mitad de la información.
    """
    await manager.send(
        user_id,
        {
            "tipo": "chat_runtime",
            "event": "engine_step",
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "paso": tipo[:120],
            "estado": estado[:60],
            "detalle": detalle[:300],
        },
    )


async def fragmento_chat(
    user_id: str,
    conversation_id: str,
    turn_id: str,
    delta: str,
    *,
    reset: bool = False,
    boundary: bool = False,
) -> None:
    """Envía texto del turno. `boundary` cierra el bloque sin cerrar el turno.

    Lo marca el fragmento que precede a una herramienta: el canal de voz lo
    necesita para locutar ya ese texto, que si no se quedaría esperando a la
    frase siguiente hasta que la herramienta termine.
    """
    await manager.send(
        user_id,
        {
            "tipo": "chat_runtime",
            "event": "delta",
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "delta": delta,
            "reset": reset,
            "boundary": boundary,
        },
    )


async def fin_respuesta_chat(
    user_id: str, conversation_id: str, turn_id: str
) -> None:
    await manager.send(
        user_id,
        {
            "tipo": "chat_runtime",
            "event": "finished",
            "conversation_id": conversation_id,
            "turn_id": turn_id,
        },
    )


async def conversacion_reiniciada(user_id: str, conversation: dict) -> None:
    await manager.send(
        user_id,
        {
            "tipo": "conversation_reset",
            "conversation_id": conversation["id"],
            "conversation_created_at": conversation["created_at"],
            "thinking_enabled": bool(conversation.get("thinking_enabled")),
        },
    )


async def archivo_actualizado(user_id: str, file: dict) -> None:
    await manager.send(
        user_id,
        {"tipo": "archivo_actualizado", "archivo": serializar_archivo(file)},
    )


async def archivo_eliminado(user_id: str, file_id: str) -> None:
    await manager.send(
        user_id,
        {"tipo": "archivo_eliminado", "archivo_id": file_id},
    )


@router.websocket("/api/eventos")
async def eventos(websocket: WebSocket) -> None:
    # El token viaja en el primer frame, no en la URL (que suele quedar en logs).
    await websocket.accept()
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        token = message.get("token", "") if isinstance(message, dict) else ""
    except Exception:  # noqa: BLE001
        await websocket.close(code=4401, reason="Autenticación requerida")
        return
    try:
        user = auth.user_from_token(token)
    except RuntimeError:
        user = None
    if not user:
        await websocket.close(code=4401, reason="Token inválido o caducado")
        return

    device_id = str(message.get("device_id", "")).strip()
    device_type = str(message.get("device_type", "")).strip()
    raw_name = message.get("device_name")
    device_name = str(raw_name).strip()[:120] if raw_name else None
    if not device_id or len(device_id) > 200 or device_type not in db.DEVICE_TYPES:
        await websocket.close(code=4400, reason="Identidad de dispositivo inválida")
        return
    if not db.upsert_device(device_id, user["id"], device_type, device_name):
        await websocket.close(code=4403, reason="Dispositivo vinculado a otro usuario")
        return

    await manager.connect(user["id"], device_id, websocket, accept=False)
    await websocket.send_json({"tipo": "conexion_lista", "device_id": device_id})
    try:
        while True:
            incoming = await websocket.receive_json()
            db.touch_device(device_id, user["id"])
            if isinstance(incoming, dict) and incoming.get("tipo") == "ping":
                await websocket.send_json({"tipo": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(user["id"], device_id, websocket)
    except Exception:  # noqa: BLE001
        manager.disconnect(user["id"], device_id, websocket)
        log.exception("WebSocket interrumpido para %s", user["id"])

"""WebSocket autenticado y difusión de eventos por usuario."""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth, db
from .serializers import serializar_archivo, serializar_mensaje, serializar_tarea

log = logging.getLogger("morgana.events")


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


async def tarea_actualizada(user_id: str, task: dict) -> None:
    await manager.send(
        user_id,
        {"tipo": "tarea_actualizada", "task": serializar_tarea(task)},
    )


async def mensaje_chat(user_id: str, message: dict) -> None:
    await manager.send_active_message(user_id, message)


async def conversacion_reiniciada(user_id: str, conversation: dict) -> None:
    await manager.send(
        user_id,
        {
            "tipo": "conversation_reset",
            "conversation_id": conversation["id"],
            "conversation_created_at": conversation["created_at"],
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

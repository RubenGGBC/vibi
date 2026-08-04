"""Malla de nodos ejecutores: alta, presencia y cola de órdenes.

Un nodo es una máquina del usuario (el PC main, el MacBook) donde corre el
agente de `agent/`. El agente abre la conexión hacia Morgana, nunca al revés:
así no hay puertos que abrir ni NAT que atravesar.

Este módulo es el espejo de `events.py`, pero para máquinas en vez de para
ventanas del navegador: allí se difunde a todas las conexiones del usuario,
aquí se dirige una orden a un destinatario concreto y se espera su resultado.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import db, events
from .config import settings

log = logging.getLogger("morgana.nodes")

# Capacidades que el servidor acepta emitir. El agente valida otra vez por su
# cuenta: ninguna de las dos partes se fía de la lista de la otra.
CAPABILITIES = ("ping", "projects.list")

MAX_RESULT_BYTES = 200_000


class NodeError(Exception):
    pass


class NodeNotFound(NodeError):
    pass


class NodeAmbiguous(NodeError):
    """El nombre encaja con más de un nodo: mejor preguntar que adivinar."""


class NodeOffline(NodeError):
    pass


class UnsupportedCapability(NodeError):
    pass


# ---------- Tokens ----------

def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def issue_token(node_id: str) -> tuple[str, str]:
    """Devuelve (token en claro, hash a guardar).

    El token lleva delante el id del nodo para poder localizar la fila sin
    recorrer la tabla entera comparando hashes.
    """
    secret = secrets.token_urlsafe(32)
    return f"{node_id}.{secret}", _hash_secret(secret)


def node_from_token(token: str) -> dict | None:
    node_id, _, secret = token.partition(".")
    if not node_id or not secret:
        return None
    node = db.get_node(node_id)
    if not node or node["estado"] != "activo":
        return None
    if not hmac.compare_digest(node["token_hash"], _hash_secret(secret)):
        return None
    return node


# ---------- Alta y consulta ----------

def register(user: dict, nombre: str, plataforma: str) -> tuple[dict, str]:
    """Da de alta un nodo y emite su token. El token solo se ve aquí una vez."""
    nombre = " ".join(nombre.split()).strip()
    if not nombre:
        raise NodeError("El nodo necesita un nombre")

    # El token lleva dentro el id del nodo, así que el id se genera antes de
    # insertar y la fila nace ya con su hash definitivo.
    node_id = str(uuid.uuid4())
    token, token_hash = issue_token(node_id)
    node = db.create_node(user["id"], nombre, plataforma, token_hash, node_id)
    db.log_event("nodo_registrado", user["id"], node_id=node_id, nombre=nombre)
    return node, token


def resolve(user_id: str, reference: str) -> dict:
    """Localiza un nodo por id o por nombre, como lo diría una persona."""
    reference = " ".join(str(reference or "").split()).strip()
    if not reference:
        raise NodeNotFound("No has dicho a qué dispositivo")

    nodes = db.list_nodes(user_id)
    for node in nodes:
        if node["id"] == reference:
            return node

    lowered = reference.casefold()
    exact = [node for node in nodes if node["nombre"].casefold() == lowered]
    if len(exact) == 1:
        return exact[0]

    partial = [node for node in nodes if lowered in node["nombre"].casefold()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise NodeAmbiguous(
            "Hay varios dispositivos que encajan: "
            + ", ".join(node["nombre"] for node in partial)
        )
    raise NodeNotFound(f"No tienes ningún dispositivo llamado «{reference}»")


def serialize(node: dict, *, online: bool | None = None) -> dict:
    return {
        "id": node["id"],
        "nombre": node["nombre"],
        "plataforma": node["plataforma"],
        "estado": node["estado"],
        "capacidades": node["capacidades"],
        "conectado": manager.is_online(node["id"]) if online is None else online,
        "last_seen": node["last_seen"],
        "created_at": node["created_at"],
    }


# ---------- Conexiones vivas ----------

class NodeConnectionManager:
    """Una conexión por nodo: si el agente se reinicia, la nueva sustituye."""

    def __init__(self) -> None:
        self.connections: dict[str, WebSocket] = {}
        self._results: dict[str, asyncio.Future] = {}

    async def connect(self, node_id: str, websocket: WebSocket) -> None:
        previous = self.connections.get(node_id)
        self.connections[node_id] = websocket
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4409, reason="Conexión sustituida")
            except Exception:  # noqa: BLE001 - la vieja ya podía estar muerta
                pass

    def disconnect(self, node_id: str, websocket: WebSocket) -> None:
        if self.connections.get(node_id) is websocket:
            self.connections.pop(node_id, None)

    def is_online(self, node_id: str) -> bool:
        return node_id in self.connections

    async def send(self, node_id: str, payload: dict) -> bool:
        websocket = self.connections.get(node_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001
            self.disconnect(node_id, websocket)
            return False
        return True

    def expect_result(self, order_id: str) -> asyncio.Future:
        future = asyncio.get_running_loop().create_future()
        self._results[order_id] = future
        return future

    def forget_result(self, order_id: str) -> None:
        self._results.pop(order_id, None)

    def deliver_result(self, order_id: str, order: dict) -> None:
        future = self._results.pop(order_id, None)
        if future is not None and not future.done():
            future.set_result(order)


manager = NodeConnectionManager()
router = APIRouter()


# ---------- Emisión de órdenes ----------

async def dispatch(
    user: dict,
    node: dict,
    capability: str,
    arguments: dict | None = None,
    *,
    queue_if_offline: bool = True,
) -> dict:
    """Emite una orden y espera su resultado mientras merezca la pena esperar.

    Devuelve siempre un dict con `estado`: `ok`, `error`, `pendiente` (el nodo
    está apagado y la recogerá al encender) o `timeout` (contestó tarde; la
    orden sigue viva y su resultado quedará registrado).
    """
    if capability not in CAPABILITIES:
        raise UnsupportedCapability(f"Capacidad no soportada: {capability}")
    if node["estado"] != "activo":
        raise NodeNotFound("Ese dispositivo está revocado")

    online = manager.is_online(node["id"])
    if not online and not queue_if_offline:
        raise NodeOffline(f"{node['nombre']} no está conectado ahora mismo")

    order = await asyncio.to_thread(
        db.create_node_order,
        node["id"],
        user["id"],
        capability,
        arguments or {},
        settings.node_order_ttl_seconds,
    )
    db.log_event(
        "nodo_orden_emitida",
        user["id"],
        node_id=node["id"],
        order_id=order["id"],
        capability=capability,
    )

    if not online:
        return {
            "estado": "pendiente",
            "order_id": order["id"],
            "node": serialize(node, online=False),
            "mensaje": (
                f"{node['nombre']} no está conectado. La orden queda pendiente "
                "y se ejecutará en cuanto vuelva a encenderse."
            ),
        }

    future = manager.expect_result(order["id"])
    entregada = await manager.send(
        node["id"],
        {
            "tipo": "orden",
            "id": order["id"],
            "capability": capability,
            "arguments": order["arguments"],
        },
    )
    if not entregada:
        manager.forget_result(order["id"])
        return {
            "estado": "pendiente",
            "order_id": order["id"],
            "node": serialize(node, online=False),
            "mensaje": (
                f"Se perdió la conexión con {node['nombre']}. La orden queda "
                "pendiente para cuando vuelva."
            ),
        }
    await asyncio.to_thread(db.mark_node_order_delivered, order["id"])

    try:
        finished = await asyncio.wait_for(
            future, timeout=settings.node_result_timeout_seconds
        )
    except asyncio.TimeoutError:
        manager.forget_result(order["id"])
        return {
            "estado": "timeout",
            "order_id": order["id"],
            "node": serialize(node),
            "mensaje": (
                f"{node['nombre']} ha recibido la orden pero aún no ha "
                "contestado. El resultado quedará en Actividad."
            ),
        }

    return {
        "estado": finished["estado"],
        "order_id": order["id"],
        "node": serialize(node),
        "resultado": finished["resultado"],
    }


# ---------- Caducidad ----------

async def expiry_worker(interval_seconds: float = 60.0) -> None:
    """Caduca órdenes que nadie recogió. Nunca reintenta: eso lo decides tú."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            expiradas = await asyncio.to_thread(db.expire_node_orders)
            for order in expiradas:
                manager.forget_result(order["id"])
                db.log_event(
                    "nodo_orden_caducada",
                    order["user_id"],
                    node_id=order["node_id"],
                    order_id=order["id"],
                    capability=order["capability"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Fallo caducando órdenes de nodos")


# ---------- WebSocket del agente ----------

async def _notificar_presencia(user_id: str, node: dict, conectado: bool) -> None:
    await events.manager.send(
        user_id,
        {
            "tipo": "nodo_presencia",
            "nodo": serialize(node, online=conectado),
        },
    )


def _sane_capabilities(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str) and item in CAPABILITIES]


@router.websocket("/api/nodos/ws")
async def nodo_ws(websocket: WebSocket) -> None:
    # Mismo criterio que /api/eventos: el token viaja en el primer frame,
    # nunca en la URL, que suele acabar en los logs del proxy.
    await websocket.accept()
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except Exception:  # noqa: BLE001
        await websocket.close(code=4401, reason="Autenticación requerida")
        return
    if not isinstance(hello, dict):
        await websocket.close(code=4400, reason="Saludo inválido")
        return

    node = node_from_token(str(hello.get("token", "")))
    if not node:
        await websocket.close(code=4401, reason="Token de nodo inválido o revocado")
        return

    capacidades = _sane_capabilities(hello.get("capacidades"))
    await asyncio.to_thread(db.touch_node, node["id"], capacidades)
    node = db.get_node(node["id"])
    await manager.connect(node["id"], websocket)
    await websocket.send_json(
        {
            "tipo": "conexion_lista",
            "node_id": node["id"],
            "nombre": node["nombre"],
            "capacidades_soportadas": list(CAPABILITIES),
        }
    )
    db.log_event("nodo_conectado", node["user_id"], node_id=node["id"])
    await _notificar_presencia(node["user_id"], node, True)

    # Lo que se quedó pendiente mientras la máquina estaba apagada.
    for order in await asyncio.to_thread(db.claim_node_orders, node["id"]):
        await websocket.send_json(
            {
                "tipo": "orden",
                "id": order["id"],
                "capability": order["capability"],
                "arguments": order["arguments"],
            }
        )

    try:
        while True:
            incoming = await websocket.receive_json()
            if not isinstance(incoming, dict):
                continue
            tipo = incoming.get("tipo")
            if tipo == "ping":
                await asyncio.to_thread(db.touch_node, node["id"])
                await websocket.send_json({"tipo": "pong"})
            elif tipo == "resultado":
                await _recibir_resultado(node, incoming)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("WebSocket de nodo interrumpido: %s", node["id"])
    finally:
        manager.disconnect(node["id"], websocket)
        db.log_event("nodo_desconectado", node["user_id"], node_id=node["id"])
        await _notificar_presencia(node["user_id"], db.get_node(node["id"]), False)


async def _recibir_resultado(node: dict, message: dict) -> None:
    order_id = str(message.get("id", ""))
    estado = message.get("estado")
    if estado not in ("ok", "error"):
        return
    resultado = message.get("resultado")
    if not isinstance(resultado, dict):
        resultado = {"detalle": str(resultado)[:500]} if resultado else {}
    # Un nodo comprometido no puede llenar la base de datos ni el contexto
    # del modelo con un resultado enorme.
    if len(str(resultado)) > MAX_RESULT_BYTES:
        estado = "error"
        resultado = {"error": "El nodo devolvió un resultado demasiado grande"}

    finished = await asyncio.to_thread(
        db.finish_node_order, order_id, node["id"], estado, resultado
    )
    if finished is None:
        return
    await asyncio.to_thread(db.touch_node, node["id"])
    db.log_event(
        "nodo_orden_resultado",
        node["user_id"],
        node_id=node["id"],
        order_id=order_id,
        capability=finished["capability"],
        estado=estado,
    )
    manager.deliver_result(order_id, finished)

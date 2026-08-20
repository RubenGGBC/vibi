"""Malla de nodos ejecutores: alta, presencia y cola de órdenes.

Un nodo es una máquina del usuario (el PC main, el MacBook) donde corre el
agente de `agent/`. El agente abre la conexión hacia Vibi, nunca al revés:
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
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from . import db, events, taint
from .config import settings

log = logging.getLogger("vibi.nodes")

# Capacidades que el servidor acepta emitir. El agente valida otra vez por su
# cuenta: ninguna de las dos partes se fía de la lista de la otra.
CAPABILITIES = (
    "ping",
    "projects.list",
    "shell.run",
    "browser.open",
    "browser.mcp",
    "system.mcp",
    "apps.launch",
    "open.path",
    "files.search",
    "files.stat",
    "files.push",
    "files.pull",
    "media.control",
    "media.now_playing",
    "screen.capture",
    "screen.click",
    "screen.move",
    "screen.drag",
    "screen.scroll",
    "screen.type",
    "screen.key",
    "ui.snapshot",
    "ui.batch",
    "web.apps",
    "web.evaluar",
    "trastienda.abrir",
    "trastienda.estado",
)

# El ratón y el teclado, que van juntos a todos los efectos: son la mano con la
# que Vibi toca lo que acaba de ver en `screen.capture`.
CAPACIDADES_ENTRADA = frozenset(
    {
        "screen.click",
        "screen.move",
        "screen.drag",
        "screen.scroll",
        "screen.type",
        "screen.key",
        # Un lote del árbol de accesibilidad es exactamente esto: clics y
        # texto. Que apunte por nombre en vez de por coordenadas lo hace más
        # certero, no más inofensivo —pulsa «Eliminar» igual de bien—, y
        # además hace varias cosas seguidas sin que nadie mire entre medias.
        "ui.batch",
        # Ejecutar JavaScript dentro de una aplicación hace lo mismo que
        # pulsar en ella, y con menos fricción: no necesita que la ventana
        # esté delante. Que sea más limpio no lo hace más inofensivo.
        "web.evaluar",
    }
)

# Capacidades que no cambian nada en la máquina de destino.
CAPACIDADES_LECTURA = frozenset(
    {
        "ping",
        "projects.list",
        "files.search",
        "files.stat",
        "media.now_playing",
        # Fotografiar la pantalla no cambia nada en la máquina: se mira, no se
        # toca. (Con la ejecución apagada por dispositivo sigue sin poder
        # pedirse a secas, porque `tools.resolve_device` solo propone máquinas
        # con `shell_habilitado`; hay que nombrar el dispositivo.)
        "screen.capture",
        # Leer el árbol de accesibilidad es mirar la misma pantalla por otra
        # ventana: se lee lo que la aplicación ya publica para los lectores de
        # pantalla y no se toca nada.
        "ui.snapshot",
        # Preguntar con qué aplicaciones se puede hablar por dentro es mirar
        # qué puertos contestan. No abre nada ni cambia nada.
        "web.apps",
        # Y preguntar qué hay en la trastienda es mirar un escritorio que
        # nadie está viendo: no toca la pantalla de nadie.
        "trastienda.estado",
    }
)

# Actúan delante de ti. El efecto es visible al instante y se deshace cerrando
# una ventana o volviendo a dar al play, así que no merecen interrumpirte con
# un diálogo salvo que la idea venga de contenido que Vibi acaba de leer.
CAPACIDADES_ESCRITORIO = frozenset(
    {
        "browser.open",
        "browser.mcp",
        "system.mcp",
        "apps.launch",
        "open.path",
        "media.control",
        # Abrir algo en la trastienda es lo contrario de actuar delante de
        # ti: no se ve. Va aquí igualmente porque arranca un programa, que es
        # lo que decide la categoría.
        "trastienda.abrir",
    }
)

# Capacidades cuyo resultado mete en el contexto texto que no has escrito tú.
#
# La lista existe para no contaminar de más: abrir una URL que hemos construido
# nosotros, o pausar la música, no traen de vuelta ni una palabra ajena. Marcar
# esas también obligaba a confirmar el siguiente comando por nada, y convertía
# poner dos canciones seguidas en dos diálogos de permiso.
CAPACIDADES_CON_CONTENIDO_AJENO = frozenset(
    {
        "shell.run",
        "files.search",
        # Lo que devuelve una página web lo ha escrito cualquiera: es el mismo
        # contenido ajeno que trae una captura o un árbol.
        "web.evaluar",
        # Preguntar cuánto pesa un archivo cuya ruta acabas de dar tú no mete
        # texto ajeno en el contexto; traérselo entero, sí.
        "files.push",
        "projects.list",
        "media.now_playing",
        # En tu pantalla puede haber cualquier cosa: una web abierta, un correo
        # de un desconocido, el README de un repo ajeno. Que llegue como imagen
        # y no como texto no lo convierte en algo que hayas escrito tú.
        "screen.capture",
    }
)

MAX_RESULT_BYTES = 200_000

# Cuánto puede esperar el nodo a tener delante la pestaña del vídeo recién
# abierto antes de darle al play. Medido en Windows 11 con Zen: la ventana toma
# el foco a 1,3 s y la pestaña nueva pasa a primer plano a 3,3 s. El resto es
# margen para una máquina cargada; no se paga salvo que el vídeo tarde o que
# estés mirando otra ventana, porque en cuanto la pestaña aparece se corta.
ESPERA_ARRANQUE_SEGUNDOS = 8.0

# Clientes que se registran como nodo solo para tener credencial de voz. No
# corren el agente, así que prometer que ejecutan sería mentira.
PLATAFORMAS_SIN_EJECUCION = frozenset({"windows-companion"})

# Binarios cuyo único efecto es mirar. La lista NO es una medida de seguridad
# —cualquiera se salta con `echo ... | sh`, y por eso la presencia de tuberías
# o sustituciones descarta el auto-aprobado— sino de comodidad: sirve para no
# preguntarte por un `ls` cuarenta veces al día. Lo que no esté aquí, pregunta.
BINARIOS_SOLO_LECTURA = frozenset({
    "cat", "cd", "date", "df", "dir", "du", "echo", "file", "find", "grep",
    "head", "hostname", "ls", "printenv", "ps", "pwd", "sort", "stat", "tail",
    "tree", "uname", "uniq", "uptime", "wc", "whereis", "which", "whoami",
})

# Subcomandos de git que solo consultan. `git` a secas no vale: `git push` y
# `git clean` viven en el mismo binario.
GIT_SOLO_LECTURA = frozenset({
    "branch", "diff", "log", "remote", "show", "status", "tag",
})

# Construcciones que permiten encadenar o generar comandos nuevos. Su sola
# presencia manda el comando a confirmación, sin mirar nada más.
METACARACTERES = ("|", ">", "<", ";", "&", "$", "`", "\n")


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


class ShellDeshabilitado(NodeError):
    """El nodo tiene la ejecución apagada: ni se encola ni se pregunta."""


# ---------- Riesgo y consentimiento ----------

def _comando_solo_lectura(comando: str) -> bool:
    """¿Es tan obviamente inocuo que preguntar sería ruido?

    Conservadora a propósito: ante la mínima duda devuelve False y el comando
    acaba pasando por ti. Un falso negativo cuesta un clic; un falso positivo
    ejecuta algo a tus espaldas.
    """
    comando = comando.strip()
    if not comando or any(caracter in comando for caracter in METACARACTERES):
        return False

    piezas = comando.split()
    binario = piezas[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].casefold()

    if binario == "git":
        subcomando = next(
            (pieza for pieza in piezas[1:] if not pieza.startswith("-")), ""
        )
        return subcomando.casefold() in GIT_SOLO_LECTURA

    return binario in BINARIOS_SOLO_LECTURA


def evaluar_riesgo(user_id: str, capability: str, arguments: dict) -> str:
    """Cómo de gordo es lo que va a pasar. Solo informa: no detiene nada.

    Queda registrado en Actividad y viaja en la orden, así que después se puede
    mirar qué se ejecutó y con qué peso. Ya no decide.
    """
    if capability in CAPACIDADES_LECTURA:
        return "bajo"
    if capability in CAPACIDADES_ESCRITORIO:
        return "medio" if taint.registro.contaminado(user_id) else "bajo"
    if capability in CAPACIDADES_ENTRADA:
        # Mover el puntero no cambia nada: se sitúa, no pulsa.
        if capability == "screen.move":
            return "bajo"
        # Pinchar y teclear pueden llegar tan lejos como llegue lo que haya
        # abierto: un clic aterriza en «Eliminar» igual que en «Guardar», y un
        # teclado que escribe donde esté el foco puede escribir en una
        # terminal. Sube a alto en cuanto el contexto viene de fuera, que es
        # justo cuando esto se convierte en el brazo de una inyección: lo que
        # se lee en una pantalla es texto de cualquiera.
        return "alto" if taint.registro.contaminado(user_id) else "medio"
    if capability == "shell.run":
        if taint.registro.contaminado(user_id):
            return "alto"
        return "bajo" if _comando_solo_lectura(
            str(arguments.get("comando") or "")
        ) else "alto"
    return "alto"


def clasificar_orden(
    user_id: str, capability: str, arguments: dict
) -> tuple[str, bool, str | None]:
    """Decide el riesgo de una orden y si hace falta tu visto bueno.

    Devuelve `(riesgo, requiere_aprobacion, motivo)`.

    **Nada requiere aprobación.** Decisión explícita del dueño de estas
    máquinas el 2026-08-05, tomada sabiendo lo que cuesta: Vibi ejecuta lo
    que decida ejecutar, también cuando la idea sale de un README, del título
    de un vídeo o de una búsqueda web. Con esto desaparece la única defensa
    real contra la inyección de prompts; lo que queda son los privilegios del
    usuario del sistema y el interruptor por dispositivo (`shell_habilitado`),
    que sí sigue funcionando y apaga la ejecución remota de golpe.

    El riesgo se sigue calculando porque sirve para mirar atrás en Actividad.
    Para devolver las confirmaciones, este `False` vuelve a ser el resultado de
    `evaluar_riesgo(...) != "bajo"` y el motivo se reconstruye desde
    `taint.registro.motivo(user_id)`, que se sigue manteniendo al día.
    """
    return evaluar_riesgo(user_id, capability, arguments), False, None


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


def desde_cabecera(authorization: str | None) -> dict:
    """El nodo que hay detrás de un `Authorization: Bearer`, o 401.

    Vive aquí y no en cada módulo que sirve un endpoint al agente porque es la
    misma pregunta —de qué máquina viene esto— y tenerla escrita dos veces era
    tener dos sitios donde aflojarla por descuido.
    """
    esquema, _, token = (authorization or "").partition(" ")
    if esquema.lower() != "bearer" or not token:
        raise HTTPException(401, "Falta el token del dispositivo")
    node = node_from_token(token.strip())
    if node is None:
        raise HTTPException(401, "Token de dispositivo inválido o revocado")
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

    # El companion de escritorio se da de alta como nodo para tener una
    # credencial revocable de voz, pero no corre el agente: nunca abre el
    # WebSocket de órdenes y por tanto no puede ejecutar nada. Nace con la
    # ejecución apagada para que no aparezca como candidato cuando haya que
    # decidir en qué máquina hacer algo.
    if plataforma in PLATAFORMAS_SIN_EJECUCION:
        db.set_node_shell(node_id, user["id"], False)
        node = db.get_node(node_id)

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
        "shell_habilitado": bool(node.get("shell_habilitado", 1)),
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

    def online_ids(self) -> tuple[str, ...]:
        """Los nodos conectados ahora mismo, sin mirar de quién son."""
        return tuple(self.connections)

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

# A quién avisar cuando una orden termina. Existe para las órdenes que nadie
# está esperando en vivo: la que recoge una máquina al encenderse llega horas
# después, cuando quien la pidió ya se fue, y alguien tiene que enterarse.
_observador_ordenes: Callable[[dict, dict], Awaitable[None]] | None = None


def registrar_observador_ordenes(
    callback: Callable[[dict, dict], Awaitable[None]],
) -> None:
    global _observador_ordenes
    _observador_ordenes = callback


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

    arguments = arguments or {}
    if capability not in CAPACIDADES_LECTURA and not node.get("shell_habilitado", 1):
        raise ShellDeshabilitado(
            f"{node['nombre']} tiene la ejecución remota apagada. Vuelve a "
            "encenderla desde Dispositivos si quieres que obedezca."
        )

    # Un agente viejo declara menos capacidades de las que el servidor conoce.
    # Mejor decirlo ahora que encolar una orden que va a rebotar dentro de seis
    # horas. Si nunca se ha conectado, la lista está vacía y no sabemos nada:
    # en ese caso se deja pasar y ya contestará él.
    declaradas = node.get("capacidades") or []
    if declaradas and capability not in declaradas:
        raise UnsupportedCapability(
            f"{node['nombre']} no sabe hacer «{capability}». Puede que su "
            "agente sea una versión anterior: actualízalo y reinícialo."
        )

    riesgo, requiere_aprobacion, motivo = clasificar_orden(
        user["id"], capability, arguments
    )

    online = manager.is_online(node["id"])
    if not online and not queue_if_offline:
        raise NodeOffline(f"{node['nombre']} no está conectado ahora mismo")

    order = await asyncio.to_thread(
        db.create_node_order,
        node["id"],
        user["id"],
        capability,
        arguments,
        settings.node_order_ttl_seconds,
        "pendiente" if requiere_aprobacion else "no_requiere",
        riesgo,
        motivo,
        # Una acción interactiva no debe revivir al reconectar. Se registra
        # como intento de entrega desde el nacimiento para que `claim_node_orders`
        # nunca pueda recogerla durante una carrera de desconexión.
        queue_if_offline or requiere_aprobacion,
    )
    db.log_event(
        "nodo_orden_emitida",
        user["id"],
        node_id=node["id"],
        order_id=order["id"],
        capability=capability,
        riesgo=riesgo,
        aprobacion=order["aprobacion"],
    )

    if requiere_aprobacion:
        await _notificar_aprobacion(user["id"], node, order)
        return {
            "estado": "esperando_aprobacion",
            "order_id": order["id"],
            "node": serialize(node, online=online),
            "riesgo": riesgo,
            "motivo": motivo,
            "mensaje": (
                f"Esta orden para {node['nombre']} necesita tu visto bueno. "
                "Te la he dejado en Vibi para que la apruebes o la rechaces; "
                "hasta entonces no se ejecuta."
            ),
        }

    return await entregar_y_esperar(
        user, node, order, queue_if_offline=queue_if_offline
    )


async def entregar_y_esperar(
    user: dict,
    node: dict,
    order: dict,
    *,
    queue_if_offline: bool = True,
) -> dict:
    """Manda una orden ya autorizada al nodo y espera lo que tarde en llegar.

    Vive separada de `dispatch` porque hay dos caminos hasta aquí: la orden que
    no necesitaba permiso y la que acabas de aprobar minutos después.
    """
    if not manager.is_online(node["id"]):
        if not queue_if_offline:
            await asyncio.to_thread(
                db.cancel_node_order,
                order["id"],
                user["id"],
                "Cancelada porque el dispositivo se desconectó antes del envío",
            )
            return {
                "estado": "offline",
                "order_id": order["id"],
                "node": serialize(node, online=False),
                "mensaje": f"{node['nombre']} se desconectó antes de recibir la orden.",
            }
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
            "capability": order["capability"],
            "arguments": order["arguments"],
        },
    )
    if not entregada:
        manager.forget_result(order["id"])
        if not queue_if_offline:
            await asyncio.to_thread(
                db.cancel_node_order,
                order["id"],
                user["id"],
                "Cancelada tras perder la conexión durante el envío",
            )
            # El envío puede haber alcanzado al sistema aunque el WebSocket
            # fallara al confirmarlo. Es terminal: reintentar con el modelo
            # podría abrir la aplicación dos veces.
            return {
                "estado": "timeout",
                "order_id": order["id"],
                "node": serialize(node, online=False),
                "mensaje": (
                    f"Se perdió la conexión con {node['nombre']} durante el envío; "
                    "la orden no se reintentará."
                ),
            }
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

    # Lo que vuelve de otra máquina es contenido que Vibi no ha escrito: a
    # partir de aquí el contexto está contaminado y el siguiente comando pasa
    # por el usuario. Solo cuenta lo que de verdad trae texto ajeno: ver
    # `CAPACIDADES_CON_CONTENIDO_AJENO`.
    if (
        finished["estado"] == "ok"
        and order["capability"] in CAPACIDADES_CON_CONTENIDO_AJENO
    ):
        fuente = f"devices.{order['capability']}"
        taint.registro.marcar(
            user["id"],
            fuente,
            # Si el catálogo tiene una frase propia para esta fuente, gana:
            # dice *qué* se leyó y no solo de dónde vino, y esa frase es la que
            # acabas leyendo en la tarjeta cuando te pedimos permiso.
            None
            if fuente in taint.FUENTES_EXTERNAS
            else f"la respuesta de {node['nombre']}",
        )

    return {
        "estado": finished["estado"],
        "order_id": order["id"],
        "node": serialize(node),
        "resultado": finished["resultado"],
    }


# ---------- Consentimiento ----------

def serialize_order(order: dict, node: dict | None = None) -> dict:
    payload = {
        "id": order["id"],
        "node_id": order["node_id"],
        "capability": order["capability"],
        "arguments": order["arguments"],
        "estado": order["estado"],
        "aprobacion": order.get("aprobacion", "no_requiere"),
        "riesgo": order.get("riesgo", "bajo"),
        "motivo": order.get("motivo_aprobacion"),
        "created_at": order["created_at"],
        "expires_at": order["expires_at"],
    }
    if node is not None:
        payload["node_nombre"] = node["nombre"]
    return payload


async def _notificar_aprobacion(user_id: str, node: dict, order: dict) -> None:
    await events.manager.send(
        user_id,
        {"tipo": "nodo_orden_aprobacion", "orden": serialize_order(order, node)},
    )


async def _notificar_resolucion(user_id: str, order: dict) -> None:
    await events.manager.send(
        user_id,
        {"tipo": "nodo_orden_resuelta", "orden": serialize_order(order)},
    )


async def aprobar(user: dict, order_id: str) -> dict:
    """Ejecuta lo que estaba esperando tu visto bueno."""
    order = await asyncio.to_thread(db.approve_node_order, order_id, user["id"])
    if order is None:
        raise NodeNotFound("Esa orden ya no está esperando aprobación")

    node = db.get_node_for_user(order["node_id"], user["id"])
    if node is None:
        raise NodeNotFound("El dispositivo de esa orden ya no existe")

    # Puede haber pasado un rato entre la petición y el clic: si mientras tanto
    # has apagado la ejecución en esa máquina, gana la decisión más reciente.
    if order["capability"] not in CAPACIDADES_LECTURA and not node.get(
        "shell_habilitado", 1
    ):
        await asyncio.to_thread(db.reject_node_order, order_id, user["id"])
        raise ShellDeshabilitado(
            f"{node['nombre']} tiene la ejecución remota apagada; la orden se "
            "ha descartado."
        )

    db.log_event(
        "nodo_orden_aprobada",
        user["id"],
        node_id=node["id"],
        order_id=order_id,
        capability=order["capability"],
    )
    await _notificar_resolucion(user["id"], order)
    return await entregar_y_esperar(user, node, order)


async def rechazar(user: dict, order_id: str) -> dict:
    order = await asyncio.to_thread(db.reject_node_order, order_id, user["id"])
    if order is None:
        raise NodeNotFound("Esa orden ya no está esperando aprobación")
    db.log_event(
        "nodo_orden_rechazada",
        user["id"],
        node_id=order["node_id"],
        order_id=order_id,
        capability=order["capability"],
    )
    await _notificar_resolucion(user["id"], order)
    return serialize_order(order)


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
            elif tipo == "aviso":
                # Lo único que un nodo dice sin que se lo pidan. Va aparte de
                # `resultado` a propósito: aquí no hay ninguna orden que lo
                # haya provocado, y eso tiene que verse en el protocolo.
                await _recibir_aviso(node, incoming)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("WebSocket de nodo interrumpido: %s", node["id"])
    finally:
        manager.disconnect(node["id"], websocket)
        db.log_event("nodo_desconectado", node["user_id"], node_id=node["id"])
        await _notificar_presencia(node["user_id"], db.get_node(node["id"]), False)


async def _recibir_aviso(node: dict, message: dict) -> None:
    """Una notificación del sistema que ha visto este equipo.

    Un fallo aquí no puede tumbar la sesión del nodo: al otro lado hay un bucle
    contando lo que ve, y que Vibi no sepa reformular un aviso no es motivo para
    quedarse sin el ordenador entero.
    """
    from . import avisos  # noqa: PLC0415 - circular con el canal de eventos

    try:
        await avisos.recibir(node["user_id"], message.get("aviso"))
    except Exception:  # noqa: BLE001
        log.exception("No pude procesar un aviso de %s", node["id"])


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
    if _observador_ordenes is not None:
        try:
            await _observador_ordenes(node, finished)
        except Exception:  # noqa: BLE001 - el observador no manda aquí
            log.exception("Observador de órdenes falló con %s", order_id)

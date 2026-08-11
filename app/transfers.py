"""Archivos que viajan entre los dispositivos del usuario.

El agente solo abre conexiones salientes, así que dos máquinas nunca se hablan
directamente: el origen sube, Vibi guarda, el destino baja. Lo que se guarda
no es un blob temporal sino un archivo del usuario en toda regla, con su fila en
`files` y su sitio en el workspace, para que después se pueda encontrar y leer
con las herramientas de siempre.

El contenido viaja por HTTP y no por el WebSocket de órdenes: así hay streaming
en los dos extremos, la memoria no crece con el tamaño del archivo y el canal de
órdenes queda libre. Por el WebSocket solo van los metadatos.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse

from . import db, events, files, nodes, taint
from .config import settings

log = logging.getLogger("vibi.transfers")

router = APIRouter()

# Tope de guardia para una subida que llega sin tamaño declarado. No es el
# límite del usuario —ese lo decide él confirmando— sino la defensa contra un
# nodo comprometido que intente llenar el disco del servidor.
MAX_SUBIDA_SIN_DECLARAR = 20 * 1024**3

# Margen sobre lo que declaró `files.stat`: entre la medición y la subida el
# archivo puede haber crecido un poco si algo lo estaba escribiendo.
MARGEN_TAMANO = 1.10

CANAL_TELEGRAM = "telegram"


class TransferError(Exception):
    pass


class TamanoNoConfirmado(TransferError):
    """El archivo pesa más de lo recomendado y hace falta un sí explícito."""

    def __init__(self, mensaje: str, bytes_totales: int) -> None:
        super().__init__(mensaje)
        self.bytes_totales = bytes_totales


# Quién está esperando el desenlace de una transferencia. La entrega ocurre en
# un sitio único —la tarea que lanza el endpoint de subida—, y quien pidió el
# envío se limita a esperar aquí a que aquella termine. Sin esto, la subida y la
# llamada del modelo se pisarían intentando entregar las dos.
_esperas: dict[str, asyncio.Future] = {}


def _esperar_desenlace(transfer_id: str) -> asyncio.Future:
    future = asyncio.get_running_loop().create_future()
    _esperas[transfer_id] = future
    return future


def _resolver_espera(transfer: dict) -> None:
    future = _esperas.pop(transfer["id"], None)
    if future is not None and not future.done():
        future.set_result(transfer)


# ---------- Ayudas ----------

def _nombre_de_ruta(ruta: str) -> str:
    """El último componente de una ruta, venga del SO que venga.

    El servidor corre en Linux y la ruta puede llegar de un Windows, así que
    `PurePosixPath` sola se comería `C:\\Users\\...` entero como un nombre.
    """
    limpio = str(ruta or "").strip().rstrip("/\\")
    if not limpio:
        return "archivo"
    posix = PurePosixPath(limpio).name
    windows = PureWindowsPath(limpio).name
    # Nos quedamos con el más corto de los dos: es el que de verdad separó.
    nombre = min((posix, windows), key=len) if posix and windows else (posix or windows)
    return nombre or "archivo"


def serialize(transfer: dict) -> dict:
    return {
        "id": transfer["id"],
        "nombre": transfer["nombre"],
        "estado": transfer["estado"],
        "origen_node_id": transfer["origen_node_id"],
        "destino_node_id": transfer["destino_node_id"],
        "destino_canal": transfer["destino_canal"],
        "file_id": transfer["file_id"],
        "bytes_esperados": transfer["bytes_esperados"],
        "bytes_recibidos": transfer["bytes_recibidos"],
        "error": transfer["error"],
        "created_at": transfer["created_at"],
    }


async def _notificar(user_id: str, transfer: dict) -> None:
    await events.manager.send(
        user_id, {"tipo": "transferencia", "transferencia": serialize(transfer)}
    )


async def _marcar(transfer_id: str, user_id: str, **campos) -> dict:
    transfer = await asyncio.to_thread(db.update_transfer, transfer_id, **campos)
    if transfer:
        await _notificar(user_id, transfer)
    return transfer


def _limite_recomendado(user_id: str, bytes_totales: int) -> str | None:
    """Devuelve el aviso a dar, o None si el archivo entra sin discusión."""
    if bytes_totales > settings.file_max_bytes:
        return (
            f"pesa {_legible(bytes_totales)} y el máximo recomendado por "
            f"archivo son {_legible(settings.file_max_bytes)}"
        )
    libre = settings.file_user_quota_bytes - db.managed_usage(user_id)
    if bytes_totales > libre:
        return (
            f"pesa {_legible(bytes_totales)} y solo te quedan "
            f"{_legible(max(0, libre))} de cuota"
        )
    return None


def _legible(bytes_totales: int) -> str:
    unidades = ("B", "KB", "MB", "GB", "TB")
    valor = float(max(0, bytes_totales))
    for unidad in unidades:
        if valor < 1024 or unidad == unidades[-1]:
            return f"{valor:.0f} {unidad}" if unidad == "B" else f"{valor:.1f} {unidad}"
        valor /= 1024
    return f"{valor:.1f} TB"


# ---------- Inicio de una transferencia ----------

async def medir(user: dict, origen: dict, ruta: str) -> dict:
    """Pregunta al origen cuánto pesa el archivo, antes de mover nada."""
    resultado = await nodes.dispatch(
        user, origen, "files.stat", {"ruta": ruta}, queue_if_offline=False
    )
    if resultado["estado"] != "ok":
        raise TransferError(
            resultado.get("mensaje")
            or f"{origen['nombre']} no ha podido mirar ese archivo"
        )
    datos = resultado.get("resultado") or {}
    if not datos.get("existe"):
        raise TransferError(f"No existe {ruta} en {origen['nombre']}")
    if datos.get("directorio"):
        raise TransferError(
            f"{ruta} es una carpeta, y de momento solo sé mover archivos sueltos"
        )
    return datos


async def iniciar(
    user: dict,
    origen: dict | None,
    destino: dict | None,
    ruta: str,
    *,
    destino_canal: str | None = None,
    confirmado_grande: bool = False,
) -> dict:
    """Arranca un envío desde una máquina hacia otra, hacia el móvil o a Files.

    Con `origen` a None el archivo ya está en Vibi y solo falta entregarlo.
    """
    if origen is None:
        raise TransferError("No has dicho de dónde sale el archivo")

    datos = await medir(user, origen, ruta)
    bytes_totales = int(datos.get("bytes") or 0)
    aviso = _limite_recomendado(user["id"], bytes_totales)
    if aviso and not confirmado_grande:
        raise TamanoNoConfirmado(
            f"«{_nombre_de_ruta(ruta)}» {aviso}. ¿Lo traigo igualmente?",
            bytes_totales,
        )

    transfer = await asyncio.to_thread(
        db.create_transfer,
        user["id"],
        _nombre_de_ruta(datos.get("nombre") or ruta),
        "esperando_origen",
        settings.node_order_ttl_seconds,
        origen_node_id=origen["id"],
        destino_node_id=destino["id"] if destino else None,
        destino_canal=destino_canal,
        ruta_origen=ruta,
        bytes_esperados=bytes_totales,
    )
    db.log_event(
        "transferencia_iniciada",
        user["id"],
        transfer_id=transfer["id"],
        node_id=origen["id"],
        destino=destino["id"] if destino else destino_canal,
        bytes=bytes_totales,
    )
    await _notificar(user["id"], transfer)

    # El nodo de origen sube por su cuenta; aquí solo se le dice qué y adónde.
    # La espera se registra antes de emitir la orden porque la subida puede
    # completarse mientras `dispatch` sigue bloqueado.
    desenlace = _esperar_desenlace(transfer["id"])
    try:
        resultado = await nodes.dispatch(
            user,
            origen,
            "files.push",
            {"ruta": ruta, "transfer_id": transfer["id"]},
        )
        if resultado["estado"] == "error":
            detalle = (resultado.get("resultado") or {}).get("error")
            await _marcar(
                transfer["id"],
                user["id"],
                estado="error",
                error=detalle or "El origen no pudo enviar el archivo",
            )
            raise TransferError(detalle or f"{origen['nombre']} no pudo enviarlo")

        # El desenlace lo produce la entrega, que arranca sola en cuanto el
        # contenido termina de subir. Un archivo grande o una máquina apagada
        # tardan más de lo que merece la pena esperar aquí: la transferencia
        # sigue viva y su final llegará por eventos.
        try:
            return await asyncio.wait_for(
                desenlace, timeout=settings.node_result_timeout_seconds
            )
        except asyncio.TimeoutError:
            return await asyncio.to_thread(db.get_transfer, transfer["id"])
    finally:
        _esperas.pop(transfer["id"], None)


async def desde_archivo(
    user: dict,
    file: dict,
    destino: dict | None,
    *,
    destino_canal: str | None = None,
) -> dict:
    """Entrega a un destino un archivo que Vibi ya tiene."""
    transfer = await asyncio.to_thread(
        db.create_transfer,
        user["id"],
        file["name"],
        "en_servidor",
        settings.node_order_ttl_seconds,
        destino_node_id=destino["id"] if destino else None,
        destino_canal=destino_canal,
        file_id=file["id"],
        bytes_esperados=file["size_bytes"],
        bytes_recibidos=file["size_bytes"],
    )
    await _notificar(user["id"], transfer)
    return await entregar(user, transfer)


# ---------- Entrega ----------

async def entregar(user: dict, transfer: dict) -> dict:
    """Lleva al destino un archivo que ya está en el servidor."""
    if transfer["estado"] not in ("en_servidor", "entregando"):
        return transfer
    if not transfer["file_id"]:
        return transfer

    if transfer["destino_node_id"]:
        node = db.get_node_for_user(transfer["destino_node_id"], user["id"])
        if node is None:
            return await _marcar(
                transfer["id"],
                user["id"],
                estado="error",
                error="El dispositivo de destino ya no existe",
            )
        resultado = await nodes.dispatch(
            user,
            node,
            "files.pull",
            {"transfer_id": transfer["id"], "nombre": transfer["nombre"]},
        )
        if resultado["estado"] in ("ok", "error"):
            cerrada = await cerrar_entrega(
                user["id"],
                node,
                transfer["id"],
                "entregado" if resultado["estado"] == "ok" else "error",
                resultado.get("resultado"),
            )
            # Si el cierre lo ganó el observador, la fila ya está como toca y
            # basta con leerla.
            cerrada = dict(
                cerrada or await asyncio.to_thread(db.get_transfer, transfer["id"])
            )
            if resultado["estado"] == "ok":
                cerrada["ruta_destino"] = (resultado.get("resultado") or {}).get(
                    "ruta"
                )
            return cerrada

        # Pendiente o timeout: la orden sigue viva y el nodo la recogerá al
        # encender. No es un fallo, solo que aún no ha pasado.
        return await _marcar(transfer["id"], user["id"], estado="entregando")

    if transfer["destino_canal"] == CANAL_TELEGRAM:
        entregado = await _entregar_por_telegram(user, transfer)
        cerrada = await cerrar_entrega(
            user["id"],
            None,
            transfer["id"],
            "entregado" if entregado else "error",
            None if entregado else {"error": "No se pudo entregar por Telegram"},
        )
        return cerrada or transfer

    # Sin destino: el archivo se queda en Vibi y eso ya es la entrega.
    cerrada = await cerrar_entrega(
        user["id"], None, transfer["id"], "entregado", None
    )
    return cerrada or transfer


async def _entregar_por_telegram(user: dict, transfer: dict) -> bool:
    # Import perezoso: el canal importa el core, y el core acaba importando
    # esto. Traerlo aquí rompe el ciclo sin tener que mover nada de sitio.
    from .channels import telegram

    file = db.get_file_for_user(transfer["file_id"], user["id"])
    if file is None:
        return False
    try:
        return await telegram.enviar_archivo(user["id"], file)
    except Exception:  # noqa: BLE001 - un fallo del bot no rompe la transferencia
        log.exception("No se pudo entregar %s por Telegram", transfer["id"])
        return False


# ---------- Resultados que llegan tarde ----------

async def cerrar_entrega(
    user_id: str,
    node: dict,
    transfer_id: str,
    estado: str,
    resultado: dict | None,
) -> dict | None:
    """Da por terminada una entrega, venga la noticia por donde venga.

    Devuelve la fila si este cierre fue el bueno, o None si otro se le adelantó.
    El registro en Actividad y el aviso a las ventanas cuelgan de eso: así el
    final se anuncia una sola vez aunque dos caminos lo descubran a la vez.
    """
    cerrada = await asyncio.to_thread(
        db.close_transfer,
        transfer_id,
        estado,
        None if estado == "entregado" else (
            (resultado or {}).get("error") or "El destino no pudo guardar el archivo"
        ),
    )
    if cerrada is None:
        return None

    db.log_event(
        "transferencia_entregada" if estado == "entregado" else "transferencia_fallida",
        user_id,
        transfer_id=transfer_id,
        node_id=node["id"] if node else None,
        error=cerrada["error"],
    )
    await _notificar(user_id, cerrada)
    return cerrada


async def orden_completada(node: dict, order: dict) -> None:
    """Cierra la transferencia cuando el destino recoge su orden al encender.

    Un `files.pull` encolado puede ejecutarse horas después, cuando ya nadie
    espera respuesta. Sin esto el archivo llegaría igual pero la transferencia
    se quedaría eternamente en «entregando» hasta caducar, diciendo lo
    contrario de lo que pasó.
    """
    if order["capability"] != "files.pull":
        return
    transfer_id = str((order.get("arguments") or {}).get("transfer_id") or "")
    if not transfer_id:
        return
    if await asyncio.to_thread(
        db.get_transfer_for_user, transfer_id, node["user_id"]
    ) is None:
        return
    await cerrar_entrega(
        node["user_id"],
        node,
        transfer_id,
        "entregado" if order["estado"] == "ok" else "error",
        order.get("resultado"),
    )


# ---------- Endpoints del nodo ----------

def _nodo_autenticado(authorization: str | None) -> dict:
    return nodes.desde_cabecera(authorization)


@router.post("/api/nodos/transferencias/{transfer_id}/contenido")
async def subir_contenido(
    transfer_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """El nodo de origen entrega el contenido, en streaming."""
    node = _nodo_autenticado(authorization)
    transfer = await asyncio.to_thread(db.get_transfer, transfer_id)
    if transfer is None or transfer["user_id"] != node["user_id"]:
        raise HTTPException(404, "Esa transferencia no existe")
    if transfer["origen_node_id"] != node["id"]:
        raise HTTPException(403, "Esa transferencia no sale de este dispositivo")

    # Solo se sube una vez: quien llegue después se la encuentra reservada, en
    # lugar de pisar un archivo a medio escribir.
    reservada = await asyncio.to_thread(
        db.claim_transfer_upload, transfer_id, node["id"]
    )
    if reservada is None:
        raise HTTPException(409, "Esa transferencia ya no espera contenido")

    user = db.get_user_by_id(node["user_id"])
    if user is None:
        raise HTTPException(404, "El usuario de esa transferencia ya no existe")

    esperado = reservada["bytes_esperados"]
    techo = (
        int(esperado * MARGEN_TAMANO) + 1024
        if esperado
        else MAX_SUBIDA_SIN_DECLARAR
    )

    async def _cuerpo() -> AsyncIterator[bytes]:
        recibido = 0
        async for chunk in request.stream():
            recibido += len(chunk)
            if recibido > techo:
                raise HTTPException(413, "El archivo es mayor de lo declarado")
            yield chunk

    try:
        stored = await files.store_stream(
            user["id"],
            reservada["nombre"],
            _cuerpo(),
            # El tamaño ya se avisó y se confirmó antes de emitir la orden: aquí
            # volver a chocar contra el límite solo serviría para tirar el
            # archivo después de haberlo subido entero.
            ignorar_limites=True,
        )
    except Exception as error:  # noqa: BLE001
        # Cualquier final que no sea el archivo entero —el flujo cortado, el
        # cuerpo mayor de lo declarado, un disco lleno— deja la transferencia
        # marcada. Sin esto se quedaría en «entregando» hasta caducar y nadie
        # sabría por qué no llegó nunca.
        detalle = (
            error.detail
            if isinstance(error, HTTPException)
            else str(error) or type(error).__name__
        )
        fallida = await _marcar(
            transfer_id, user["id"], estado="error", error=str(detalle)
        )
        _resolver_espera(fallida or reservada)
        db.log_event(
            "transferencia_fallida",
            user["id"],
            transfer_id=transfer_id,
            node_id=node["id"],
            error=str(detalle),
        )
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(400, str(detalle)) from error

    transfer = await _marcar(
        transfer_id,
        user["id"],
        estado="en_servidor",
        file_id=stored["id"],
        nombre=stored["name"],
        bytes_recibidos=stored["size_bytes"],
    )
    db.log_event(
        "transferencia_recibida",
        user["id"],
        transfer_id=transfer_id,
        node_id=node["id"],
        bytes=stored["size_bytes"],
    )

    # Lo que llega de otra máquina es contenido que el usuario no ha escrito.
    taint.registro.marcar(user["id"], "devices.files.push")

    # La entrega al destino no puede colgar de esta petición: el nodo de origen
    # ya ha hecho su parte y quedarse esperando al otro extremo solo alargaría
    # la subida. Se lanza aparte y el resultado viaja por eventos.
    asyncio.create_task(_entregar_en_segundo_plano(user, transfer))

    return {"estado": "recibido", "bytes": stored["size_bytes"]}


async def _entregar_en_segundo_plano(user: dict, transfer: dict) -> None:
    """Único sitio donde se entrega lo que acaba de subir un nodo.

    Quien pidió el envío está esperando el desenlace, así que el resultado se le
    pasa pase lo que pase: si esto se cayera en silencio, su llamada se quedaría
    colgada hasta agotar el tiempo de espera.
    """
    try:
        _resolver_espera(await entregar(user, transfer))
    except Exception:  # noqa: BLE001
        log.exception("Fallo entregando la transferencia %s", transfer["id"])
        fallida = await _marcar(
            transfer["id"],
            user["id"],
            estado="error",
            error="Fallo entregando el archivo al destino",
        )
        _resolver_espera(fallida or transfer)


@router.get("/api/nodos/transferencias/{transfer_id}/contenido")
async def bajar_contenido(
    transfer_id: str,
    authorization: str | None = Header(default=None),
) -> FileResponse:
    """El nodo de destino recoge el contenido. `FileResponse` da `Range` solo."""
    node = _nodo_autenticado(authorization)
    transfer = await asyncio.to_thread(db.get_transfer, transfer_id)
    if transfer is None or transfer["user_id"] != node["user_id"]:
        raise HTTPException(404, "Esa transferencia no existe")
    if transfer["destino_node_id"] != node["id"]:
        raise HTTPException(403, "Esa transferencia no es para este dispositivo")
    if not transfer["file_id"]:
        raise HTTPException(409, "Esa transferencia todavía no tiene contenido")

    file = db.get_file_for_user(transfer["file_id"], node["user_id"])
    if file is None:
        raise HTTPException(404, "El archivo ya no está disponible")
    ruta = files.path_for_file(file, node["user_id"])
    if ruta is None or not ruta.is_file():
        raise HTTPException(404, "El archivo ya no está disponible")
    return FileResponse(
        ruta,
        media_type=file["media_type"] or "application/octet-stream",
        filename=file["name"],
    )


# ---------- Caducidad ----------

async def expiry_worker(interval_seconds: float = 60.0) -> None:
    """Caduca las entregas que nadie completó. El archivo se queda."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            for transfer in await asyncio.to_thread(db.expire_transfers):
                db.log_event(
                    "transferencia_caducada",
                    transfer["user_id"],
                    transfer_id=transfer["id"],
                )
                await _notificar(transfer["user_id"], transfer)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Fallo caducando transferencias")

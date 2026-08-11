"""Capturas de pantalla de camino al modelo, y a ningún otro sitio.

Una foto de tu pantalla no es un archivo tuyo: es lo que estabas mirando en un
instante concreto, con lo que hubiera abierto. Guardarla equivaldría a ir
dejando en el disco del servidor un registro de todo lo que has tenido delante,
y eso no lo ha pedido nadie. Así que vive en memoria, el tiempo que tarda el
modelo en mirarla, y se borra al entregarla.

Por qué no viaja por el canal de órdenes, que es por donde vuelve todo lo demás
que hace un nodo: ese canal descarta cualquier resultado de más de 200 KB
(`nodes.MAX_RESULT_BYTES`), y con razón —un resultado enorme llena la base de
datos y el contexto del modelo—. Una captura pesa justo por encima de ese
límite. Así que la imagen sube por HTTP, como los archivos, y por el canal de
órdenes solo vuelve el recibo: qué pantalla era y cuánto ocupa.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, Header, HTTPException, Request

from . import nodes

log = logging.getLogger("vibi.screenshots")

router = APIRouter()

# Lo que se espera a que el nodo suba la imagen una vez ha dicho que la tiene.
# Es un margen contra la carrera entre sus dos canales, no una espera de verdad:
# el agente termina la subida antes de contestar por el WebSocket.
ESPERA_SUBIDA = 20.0

# Cuánto sobrevive una reserva que nadie recogió. Corto: si el turno se cayó a
# mitad, esa imagen ya no le interesa a nadie y solo ocupa memoria.
CADUCIDAD = 120.0

# Un JPEG de 1568 px de lado largo no llega al megabyte ni con la pantalla más
# recargada. El tope está para que un nodo comprometido no pueda llenar la
# memoria del servidor, no para acotar una captura normal.
MAX_BYTES = 8 * 1024 * 1024


@dataclass
class _Captura:
    user_id: str
    node_id: str
    creada_en: float
    llegada: asyncio.Event = field(default_factory=asyncio.Event)
    imagen: bytes | None = None


_pendientes: dict[str, _Captura] = {}


def _limpiar() -> None:
    """Tira lo que caducó. Perezoso: no merece un worker propio."""
    limite = time.monotonic() - CADUCIDAD
    for captura_id, captura in list(_pendientes.items()):
        if captura.creada_en < limite:
            _pendientes.pop(captura_id, None)


def reservar(user_id: str, node_id: str) -> str:
    """Abre el hueco donde el nodo dejará la imagen, y devuelve su nombre.

    Se reserva antes de pedir la captura porque el identificador es lo que va
    en la orden: sin él, el nodo no sabría contra qué subir.
    """
    _limpiar()
    captura_id = uuid.uuid4().hex
    _pendientes[captura_id] = _Captura(
        user_id=user_id, node_id=node_id, creada_en=time.monotonic()
    )
    return captura_id


def descartar(captura_id: str) -> None:
    """Cierra el hueco de una captura que ya no va a llegar."""
    _pendientes.pop(captura_id, None)


def depositar(captura_id: str, node_id: str, imagen: bytes) -> None:
    """El nodo entrega la imagen. Solo el nodo al que se le pidió."""
    captura = _pendientes.get(captura_id)
    if captura is None:
        raise KeyError("Esa captura ya no se espera")
    if captura.node_id != node_id:
        raise PermissionError("Esa captura no se le pidió a este dispositivo")
    captura.imagen = imagen
    captura.llegada.set()


async def recoger(captura_id: str) -> bytes:
    """Espera la imagen, la devuelve y la borra de memoria.

    Devolver y borrar son el mismo paso a propósito: mientras la imagen siga
    aquí, sigue siendo una foto de tu pantalla en la memoria del servidor.
    """
    captura = _pendientes.get(captura_id)
    if captura is None:
        raise TimeoutError("La captura caducó antes de llegar")
    try:
        await asyncio.wait_for(captura.llegada.wait(), timeout=ESPERA_SUBIDA)
    except asyncio.TimeoutError as agotado:
        raise TimeoutError(
            "El dispositivo dijo que había capturado la pantalla, pero la "
            "imagen no llegó"
        ) from agotado
    finally:
        _pendientes.pop(captura_id, None)
    return captura.imagen or b""


@router.post("/api/nodos/capturas/{captura_id}")
async def subir_captura(
    captura_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """El nodo entrega la foto de la pantalla que se le acaba de pedir."""
    node = nodes.desde_cabecera(authorization)

    imagen = bytearray()
    async for trozo in request.stream():
        imagen.extend(trozo)
        if len(imagen) > MAX_BYTES:
            raise HTTPException(413, "Esa captura es demasiado grande")
    if not imagen:
        raise HTTPException(400, "La captura venía vacía")

    try:
        depositar(captura_id, node["id"], bytes(imagen))
    except KeyError as error:
        # Lo normal es que el turno se cancelara o que la reserva caducara. No
        # es un fallo del nodo, y no hay nada que reintentar.
        raise HTTPException(409, str(error)) from error
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error

    return {"estado": "recibida", "bytes": len(imagen)}

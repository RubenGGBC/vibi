"""La foto de la escena, de la ventana del alumno al modelo.

El render ocurre en el navegador, así que es el navegador quien saca la foto.
`estudio.captura` reserva un hueco, avisa por el WebSocket y espera; la
primera ventana con Estudio abierto sube un JPEG del lienzo a ese hueco. Como
las capturas de pantalla (`app/screenshots.py`), vive solo en memoria y se
borra al entregarla.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

ESPERA = 8.0
CADUCIDAD = 60.0
MAX_BYTES = 6 * 1024 * 1024


@dataclass
class _Hueco:
    user_id: str
    creado_en: float
    llegada: asyncio.Event = field(default_factory=asyncio.Event)
    imagen: bytes | None = None


_huecos: dict[str, _Hueco] = {}


def reservar(user_id: str) -> str:
    limite = time.monotonic() - CADUCIDAD
    for clave, hueco in list(_huecos.items()):
        if hueco.creado_en < limite:
            _huecos.pop(clave, None)
    captura_id = uuid.uuid4().hex
    _huecos[captura_id] = _Hueco(user_id=user_id, creado_en=time.monotonic())
    return captura_id


def depositar(captura_id: str, user_id: str, imagen: bytes) -> None:
    hueco = _huecos.get(captura_id)
    if hueco is None or hueco.user_id != user_id:
        raise KeyError("Esa captura ya no se espera")
    if hueco.imagen is not None:
        return  # Ya llegó la de otra ventana: con una basta.
    hueco.imagen = imagen
    hueco.llegada.set()


async def recoger(captura_id: str, espera: float = ESPERA) -> bytes:
    hueco = _huecos.get(captura_id)
    if hueco is None:
        raise TimeoutError("La captura caducó")
    try:
        await asyncio.wait_for(hueco.llegada.wait(), timeout=espera)
    except asyncio.TimeoutError as agotado:
        raise TimeoutError(
            "Ninguna ventana con la sección Estudio abierta ha contestado. "
            "Pídele al usuario que la abra (menú Estudio) o sigue sin captura"
        ) from agotado
    finally:
        _huecos.pop(captura_id, None)
    return hueco.imagen or b""

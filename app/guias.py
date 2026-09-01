"""Las guías: una foto de tu pantalla con marcas, de camino a ti y a nadie más.

Hereda entera la regla de `screenshots.py` —una captura no es un archivo tuyo,
es lo que estabas mirando en un instante— y le cambia dos cosas, porque el
destinatario es otro.

**Va hacia la persona, no hacia el modelo.** Una captura la mira el modelo
dentro del turno y se borra al entregarla. Una guía la mira alguien mientras
sigue los pasos con las manos, así que tiene que seguir ahí mientras dura eso:
diez minutos en vez de dos, y una URL propia en vez de un byte de contexto.

**Y por eso mismo no entra en el transcript.** Al caducar desaparece del chat,
no se guarda en SQLite y no viaja por el WebSocket a tus otros dispositivos.
Recargar la conversación de la semana pasada no vuelve a enseñar lo que había
en tu pantalla la semana pasada. Lo que persiste es lo que Vibi escribió; la
foto era para el momento.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Response

from . import auth

router = APIRouter()

# Cuánto vive una guía. Es el tiempo de mirarla y hacer lo que dice, no el de
# archivarla: pasado eso, quien la necesite pide otra, que además enseñará la
# pantalla como esté ahora y no como estaba.
CADUCIDAD = 600.0

# Cuántas caben a la vez en memoria, entre todos los usuarios. Un tope duro
# porque son imágenes: sin él, un turno en bucle llenaría la memoria del
# servidor con fotos de una pantalla.
MAXIMO = 40


@dataclass(frozen=True)
class _Guia:
    user_id: str
    imagen: bytes
    creada_en: float


_guias: dict[str, _Guia] = {}


def _limpiar() -> None:
    """Tira lo caducado y, si aún sobran, lo más viejo. Perezoso a propósito."""
    limite = time.monotonic() - CADUCIDAD
    for guia_id, guia in list(_guias.items()):
        if guia.creada_en < limite:
            _guias.pop(guia_id, None)
    while len(_guias) > MAXIMO:
        mas_vieja = min(_guias, key=lambda clave: _guias[clave].creada_en)
        _guias.pop(mas_vieja, None)


def publicar(user_id: str, imagen: bytes) -> dict:
    """Guarda la imagen de una guía y devuelve por dónde se mira."""
    if not imagen:
        raise ValueError("Una guía sin imagen no señala nada")
    _limpiar()
    guia_id = uuid.uuid4().hex
    _guias[guia_id] = _Guia(
        user_id=user_id, imagen=imagen, creada_en=time.monotonic()
    )
    _limpiar()
    return {
        "id": guia_id,
        "imagen_url": f"/api/guias/{guia_id}/imagen",
        "caduca_en": time.time() + CADUCIDAD,
    }


def obtener(guia_id: str, user_id: str) -> bytes:
    """La imagen, si sigue viva y si es de quien la pide."""
    _limpiar()
    guia = _guias.get(guia_id)
    if guia is None:
        raise KeyError("Esa guía ya no está: caducó o nunca existió")
    if guia.user_id != user_id:
        # Mismo error que si no existiera no: aquí sí existe y es de otro, y
        # eso es un intento de mirar la pantalla de otra persona.
        raise PermissionError("Esa guía no es tuya")
    return guia.imagen


def olvidar_todo() -> None:
    """Vacía el almacén. Para las pruebas y para el apagado."""
    _guias.clear()


@router.get("/api/guias/{guia_id}/imagen")
def imagen_de_guia(
    guia_id: str, user: dict = Depends(auth.current_user)
) -> Response:
    try:
        imagen = obtener(guia_id, user["id"])
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
    return Response(
        content=imagen,
        media_type="image/jpeg",
        # Que no quede en el disco de ningún intermediario ni del navegador:
        # es una foto de una pantalla, y ya tiene su propia caducidad.
        headers={"Cache-Control": "no-store"},
    )

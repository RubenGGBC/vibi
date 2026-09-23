"""Síntesis de voz en este Mac, con el servicio de `voz_local/`.

El servicio tiene el modelo cargado y habla por HTTP en localhost; aquí solo se
le pide el audio. Si no está —no se ha instalado, se está reiniciando, el Mac
no es Apple Silicon— quien llama cae a edge-tts: Vibi no se queda muda por
tener la voz local apagada.
"""
import httpx

from ..config import settings
from .edge_speech import SintesisError

# Conectar a localhost es instantáneo o no es: si nadie escucha, se sabe en
# milisegundos y se pasa a la nube sin que se note. Generar sí lleva un rato
# con los textos largos (600 caracteres, ~5 s medidos en un M1).
_TIMEOUT = httpx.Timeout(20.0, connect=0.5)


async def sintetizar(texto: str, *, voz: str | None = None) -> bytes:
    """Devuelve un WAV con el texto locutado."""
    limpio = texto.strip()
    if not limpio:
        raise SintesisError("No hay texto que sintetizar")

    cuerpo = {"texto": limpio, "velocidad": settings.tts_local_speed}
    if voz or settings.tts_local_voice:
        cuerpo["voz"] = voz or settings.tts_local_voice
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cliente:
            respuesta = await cliente.post(
                settings.tts_local_url.rstrip("/") + "/tts", json=cuerpo
            )
    except httpx.HTTPError as error:
        raise SintesisError(f"La voz local no responde: {error}") from error
    if respuesta.status_code != 200 or not respuesta.content:
        raise SintesisError(
            f"La voz local devolvió {respuesta.status_code}: {respuesta.text[:200]}"
        )
    return respuesta.content

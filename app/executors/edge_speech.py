"""Síntesis de voz con las voces neuronales de Microsoft Edge.

El módulo se llama `edge_speech` y no `edge_tts` para no confundirse con el
paquete de terceros del mismo nombre.
"""
import edge_tts

from ..config import settings


class SintesisError(RuntimeError):
    """El servicio de voz no devolvió audio utilizable."""


async def sintetizar(texto: str, *, voz: str | None = None) -> bytes:
    """Devuelve un MP3 con el texto locutado, sin guardar nada en disco."""
    limpio = texto.strip()
    if not limpio:
        raise SintesisError("No hay texto que sintetizar")

    communicate = edge_tts.Communicate(limpio, voz or settings.tts_voice)
    audio = bytearray()
    async for evento in communicate.stream():
        if evento.get("type") == "audio" and evento.get("data"):
            audio.extend(evento["data"])

    if not audio:
        raise SintesisError("El servicio de voz no devolvió audio")
    return bytes(audio)

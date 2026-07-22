"""Transcripción de clips de voz con Groq Whisper."""
from groq import AsyncGroq

from ..config import settings

_client: AsyncGroq | None = None


def client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


async def transcribir(nombre: str, audio: bytes) -> str:
    """Devuelve una transcripción española sin conservar el audio."""
    result = await client().audio.transcriptions.create(
        file=(nombre, audio),
        model=settings.groq_speech_model,
        language="es",
        response_format="json",
        temperature=0.0,
    )
    return (result.text or "").strip()

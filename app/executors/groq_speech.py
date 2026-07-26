"""Transcripción de clips de voz con Groq Whisper."""
from groq import AsyncGroq

from .. import ai_providers
from ..config import settings

_client: AsyncGroq | None = None


def client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


async def transcribir(user_id: str, nombre: str, audio: bytes) -> str:
    """Devuelve una transcripción española sin conservar el audio."""
    resolved = ai_providers.resolve_lane(user_id, "speech")
    groq_client = (
        client()
        if resolved.api_key == settings.groq_api_key
        else AsyncGroq(api_key=resolved.api_key)
    )
    result = await groq_client.audio.transcriptions.create(
        file=(nombre, audio),
        model=resolved.model,
        language="es",
        response_format="json",
        temperature=0.0,
    )
    return (result.text or "").strip()

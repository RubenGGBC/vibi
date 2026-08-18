"""Configuración y credenciales de IA aisladas por usuario."""
from __future__ import annotations

import base64
import hashlib
from dataclasses import asdict, dataclass
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from anthropic import AsyncAnthropic
from groq import AsyncGroq

from . import db
from .config import settings

Provider = Literal["anthropic", "groq", "antigravity"]
# Antigravity no lleva API key: se autentica con la sesión de Google que el
# usuario ya tiene abierta en su CLI, así que queda fuera del almacén de claves.
CREDENTIAL_PROVIDERS: tuple[Provider, ...] = ("anthropic", "groq")
Lane = Literal["chat", "tools", "speech", "agent"]


class ProviderConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AISettings:
    chat_provider: Provider
    chat_model: str
    tools_provider: Provider
    tools_model: str
    speech_provider: Provider
    speech_model: str
    agent_provider: Provider
    agent_model: str


@dataclass(frozen=True)
class ResolvedLane:
    provider: Provider
    model: str
    api_key: str
    fallback: bool = False


def defaults() -> AISettings:
    return AISettings(
        chat_provider="anthropic",
        chat_model="claude-haiku-4-5",
        tools_provider="anthropic",
        tools_model="claude-haiku-4-5",
        speech_provider="groq",
        speech_model=settings.groq_speech_model,
        agent_provider="anthropic",
        agent_model="claude-sonnet-5",
    )


def get_settings(user_id: str) -> AISettings:
    stored = db.get_user_ai_settings(user_id)
    if not stored:
        return defaults()
    return AISettings(
        chat_provider=stored["chat_provider"],
        chat_model=stored["chat_model"],
        tools_provider=stored["tools_provider"],
        tools_model=stored["tools_model"],
        speech_provider=stored["speech_provider"],
        speech_model=stored["speech_model"],
        agent_provider=stored["agent_provider"],
        agent_model=stored["agent_model"],
    )


def save_settings(user_id: str, value: AISettings) -> AISettings:
    db.upsert_user_ai_settings(user_id, asdict(value))
    return value


def _fernet() -> Fernet:
    secret = settings.credential_encryption_key or settings.jwt_secret
    if len(secret) < 32:
        raise ProviderConfigurationError(
            "Configura CREDENTIAL_ENCRYPTION_KEY o un JWT_SECRET de al menos 32 caracteres"
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def set_api_key(user_id: str, provider: Provider, api_key: str) -> None:
    clean = api_key.strip()
    if len(clean) < 8:
        raise ProviderConfigurationError("La API key es demasiado corta")
    encrypted = _fernet().encrypt(clean.encode("utf-8")).decode("ascii")
    db.set_provider_credential(user_id, provider, encrypted)


def delete_api_key(user_id: str, provider: Provider) -> bool:
    return db.delete_provider_credential(user_id, provider)


def _personal_api_key(user_id: str, provider: Provider) -> str | None:
    encrypted = db.get_provider_credential(user_id, provider)
    if not encrypted:
        return None
    try:
        return _fernet().decrypt(encrypted.encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise ProviderConfigurationError(
            f"No se pudo descifrar la clave personal de {provider}"
        ) from error


def get_personal_api_key(user_id: str, provider: Provider) -> str | None:
    return _personal_api_key(user_id, provider)


def system_api_key(provider: Provider) -> str:
    if provider == "anthropic":
        return settings.anthropic_api_key
    if provider == "antigravity":
        return ""
    return settings.groq_api_key


def get_api_key(user_id: str, provider: Provider) -> str:
    return _personal_api_key(user_id, provider) or system_api_key(provider)


def opciones_groq(modelo: str) -> dict:
    """Lo que hay que añadirle a una llamada de Groq según qué modelo sea.

    Los `gpt-oss` razonan antes de contestar, y ese razonamiento gasta del
    mismo presupuesto de tokens que la respuesta. Con los topes cortos que se
    usan aquí —120 en un aviso, 180 en el router— se lo comen entero y
    devuelven cadena vacía: medido el 2026-08-17, 3 de 3 en el aviso, y en el
    router un 400 `json_validate_failed` con la generación en blanco. En bajo,
    ninguna vacía y unos 300 ms.

    Se decide por el nombre porque el ajuste no es universal: mandárselo a un
    modelo que no lo entiende es un 400, y `groq_model` lo puede cambiar el
    usuario desde la pantalla de configuración.
    """
    return {"reasoning_effort": "low"} if modelo.startswith("openai/gpt-oss") else {}


def credential_status(user_id: str, provider: Provider) -> dict:
    if db.get_provider_credential(user_id, provider):
        return {"configured": True, "source": "personal"}
    if system_api_key(provider):
        return {"configured": True, "source": "system"}
    return {"configured": False, "source": "none"}


def resolve_lane(user_id: str, lane: Lane) -> ResolvedLane:
    configured = get_settings(user_id)
    provider = getattr(configured, f"{lane}_provider")
    model = getattr(configured, f"{lane}_model")
    if provider == "antigravity":
        # Se autentica con la sesión de Google de la CLI del usuario: no hay
        # clave que resolver, y la disponibilidad real solo se sabe al hablarle.
        return ResolvedLane(provider, model, "")
    api_key = get_api_key(user_id, provider)
    if api_key:
        return ResolvedLane(provider, model, api_key)

    if provider == "anthropic":
        groq_key = get_api_key(user_id, "groq")
        if groq_key and lane in {"chat", "tools"}:
            return ResolvedLane("groq", settings.groq_model, groq_key, True)
    raise ProviderConfigurationError(
        f"No hay una API key configurada para {provider} en {lane}"
    )


def public_settings(user_id: str) -> dict:
    configured = get_settings(user_id)
    result = asdict(configured)
    result["credentials"] = {
        provider: credential_status(user_id, provider)
        for provider in CREDENTIAL_PROVIDERS
    }
    lanes: dict[str, dict] = {}
    for lane in ("chat", "tools", "speech", "agent"):
        try:
            resolved = resolve_lane(user_id, lane)
            lanes[lane] = {
                "provider": resolved.provider,
                "model": resolved.model,
                "fallback": resolved.fallback,
                "available": True,
            }
        except ProviderConfigurationError:
            if lane == "agent" and settings.claude_auth_mode in {
                "auto",
                "subscription",
            }:
                lanes[lane] = {
                    "provider": configured.agent_provider,
                    "model": configured.agent_model,
                    "fallback": False,
                    "available": True,
                    "authentication": "subscription",
                }
            else:
                lanes[lane] = {"available": False, "fallback": False}
    result["effective"] = lanes
    return result


async def complete_text(
    user_id: str,
    lane: Literal["chat", "tools"],
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float = 0,
    json_mode: bool = False,
) -> str:
    resolved = resolve_lane(user_id, lane)
    if resolved.provider == "antigravity":
        # Antigravity solo conversa (motor de chat propio, con su CLI viva).
        # Para clasificar o extraer JSON no sirve: aquí manda Claude.
        raise ProviderConfigurationError(
            f"Antigravity no puede resolver el carril {lane}"
        )
    if resolved.provider == "groq":
        response = await AsyncGroq(api_key=resolved.api_key).chat.completions.create(
            model=resolved.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **({"response_format": {"type": "json_object"}} if json_mode else {}),
            **opciones_groq(resolved.model),
        )
        return response.choices[0].message.content or ""

    system = "\n\n".join(
        message["content"]
        for message in messages
        if message["role"] in {"system", "developer"}
    )
    conversation = [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message["role"] in {"user", "assistant"}
    ]
    response = await AsyncAnthropic(api_key=resolved.api_key).messages.create(
        model=resolved.model,
        system=system,
        messages=conversation,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )

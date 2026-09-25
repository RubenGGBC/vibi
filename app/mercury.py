"""Cliente de Mercury, el modelo de difusión de Inception Labs.

Habla el dialecto de OpenAI (`/v1/chat/completions`), así que no hace falta
SDK: basta httpx, que ya está. Dos cosas del dialecto que NO son las de OpenAI
y que aquí se corrigen para que quien llame no tenga que saberlas:

  - **`temperature` solo admite de 0,5 a 1.** Vibi pide 0 para clasificar, y
    mandarlo tal cual es un 400. Se acota al rango.
  - **Razona antes de contestar**, y lo que razona sale del mismo tope de
    tokens. Con los topes cortos de un aviso o del router (120-180) se
    quedaría sin respuesta, igual que le pasaba a `gpt-oss` en Groq. Por eso
    `completar` va en «instant» salvo que se pida otra cosa.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from .config import settings

log = logging.getLogger("vibi.mercury")

TEMPERATURA_MIN = 0.5
TEMPERATURA_MAX = 1.0

_cliente: httpx.AsyncClient | None = None


class MercuryError(RuntimeError):
    pass


def activo() -> bool:
    """¿Es Mercury el motor principal? Interruptor y clave, las dos cosas."""
    return bool(settings.mercury_principal and settings.mercury_api_key.strip())


def cliente() -> httpx.AsyncClient:
    global _cliente
    if _cliente is None or _cliente.is_closed:
        _cliente = httpx.AsyncClient(
            base_url=settings.mercury_base_url.rstrip("/"),
            timeout=settings.mercury_timeout_seconds,
        )
    return _cliente


async def cerrar() -> None:
    global _cliente
    if _cliente is not None and not _cliente.is_closed:
        await _cliente.aclose()
    _cliente = None


def _temperatura(valor: float | None) -> float | None:
    if valor is None:
        return None
    return min(TEMPERATURA_MAX, max(TEMPERATURA_MIN, float(valor)))


def _cuerpo(
    messages: list[dict],
    *,
    model: str | None,
    max_tokens: int | None,
    temperature: float | None,
    json_mode: bool,
    reasoning_effort: str | None,
    tools: list[dict] | None,
    stream: bool,
) -> dict:
    cuerpo: dict = {
        "model": model or settings.mercury_model,
        "messages": messages,
    }
    if max_tokens:
        cuerpo["max_completion_tokens"] = max_tokens
    temperatura = _temperatura(temperature)
    if temperatura is not None:
        cuerpo["temperature"] = temperatura
    if json_mode:
        cuerpo["response_format"] = {"type": "json_object"}
    esfuerzo = reasoning_effort or settings.mercury_reasoning_effort
    if esfuerzo:
        cuerpo["reasoning_effort"] = esfuerzo
    if tools:
        cuerpo["tools"] = tools
        cuerpo["tool_choice"] = "auto"
    if stream:
        cuerpo["stream"] = True
    return cuerpo


def _cabeceras(api_key: str | None) -> dict[str, str]:
    clave = (api_key or settings.mercury_api_key).strip()
    if not clave:
        raise MercuryError("Falta MERCURY_API_KEY")
    return {"Authorization": f"Bearer {clave}"}


def _explicar(respuesta: httpx.Response) -> str:
    try:
        detalle = respuesta.json()
    except ValueError:
        detalle = respuesta.text[:300]
    return f"Mercury respondió {respuesta.status_code}: {detalle}"


async def completar(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float | None = None,
    json_mode: bool = False,
    reasoning_effort: str | None = "instant",
    model: str | None = None,
    api_key: str | None = None,
) -> str:
    """Una respuesta de texto, sin herramientas. Para el trabajo corto."""
    cuerpo = _cuerpo(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=json_mode,
        reasoning_effort=reasoning_effort,
        tools=None,
        stream=False,
    )
    cabeceras = _cabeceras(api_key)
    espera = settings.mercury_short_timeout_seconds
    try:
        respuesta = await cliente().post(
            "/chat/completions", json=cuerpo, headers=cabeceras, timeout=espera
        )
    except httpx.TimeoutException:
        # Un cuelgue suelto de la API, no un modelo lento: lo normal son
        # décimas de segundo, así que una segunda petición suele salir bien.
        log.info("Mercury no contestó en %s s; reintento una vez", espera)
        respuesta = await cliente().post(
            "/chat/completions", json=cuerpo, headers=cabeceras, timeout=espera
        )
    if respuesta.status_code >= 400:
        raise MercuryError(_explicar(respuesta))
    datos = respuesta.json()
    return (datos["choices"][0]["message"].get("content") or "").strip()


@dataclass
class LlamadaHerramienta:
    id: str
    nombre: str
    argumentos: str = ""


@dataclass
class Evento:
    """Lo que va saliendo del stream: texto, o una herramienta que empieza."""

    texto: str = ""
    herramienta: str = ""


@dataclass
class Vuelta:
    """Lo que dejó una vuelta completa del modelo."""

    texto: str = ""
    llamadas: list[LlamadaHerramienta] = field(default_factory=list)
    motivo: str = ""


async def conversar(
    messages: list[dict],
    tools: list[dict] | None,
    vuelta: Vuelta,
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> AsyncIterator[Evento]:
    """Una vuelta en streaming. Va soltando eventos y rellena `vuelta`.

    Los `tool_calls` llegan troceados por índice: el primer trozo trae id y
    nombre, los siguientes solo pedazos de argumentos. Se van cosiendo aquí.
    """
    cuerpo = _cuerpo(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=False,
        reasoning_effort=reasoning_effort,
        tools=tools,
        stream=True,
    )
    por_indice: dict[int, LlamadaHerramienta] = {}
    async with cliente().stream(
        "POST", "/chat/completions", json=cuerpo, headers=_cabeceras(api_key)
    ) as respuesta:
        if respuesta.status_code >= 400:
            await respuesta.aread()
            raise MercuryError(_explicar(respuesta))
        async for linea in respuesta.aiter_lines():
            if not linea.startswith("data:"):
                continue
            dato = linea[5:].strip()
            if not dato:
                continue
            if dato == "[DONE]":
                break
            try:
                trozo = json.loads(dato)
            except ValueError:
                log.debug("Trozo ilegible en el stream de Mercury: %s", dato[:200])
                continue
            if trozo.get("error"):
                raise MercuryError(f"Mercury cortó el stream: {trozo['error']}")
            for choice in trozo.get("choices") or []:
                delta = choice.get("delta") or {}
                contenido = delta.get("content")
                if contenido:
                    vuelta.texto += contenido
                    yield Evento(texto=contenido)
                for parcial in delta.get("tool_calls") or []:
                    indice = int(parcial.get("index") or 0)
                    funcion = parcial.get("function") or {}
                    llamada = por_indice.get(indice)
                    if llamada is None:
                        llamada = LlamadaHerramienta(
                            id=str(parcial.get("id") or f"llamada_{indice}"),
                            nombre=str(funcion.get("name") or ""),
                        )
                        por_indice[indice] = llamada
                        if llamada.nombre:
                            yield Evento(herramienta=llamada.nombre)
                    elif funcion.get("name") and not llamada.nombre:
                        llamada.nombre = str(funcion["name"])
                        yield Evento(herramienta=llamada.nombre)
                    if funcion.get("arguments"):
                        llamada.argumentos += str(funcion["arguments"])
                if choice.get("finish_reason"):
                    vuelta.motivo = str(choice["finish_reason"])
    vuelta.llamadas = [por_indice[i] for i in sorted(por_indice)]

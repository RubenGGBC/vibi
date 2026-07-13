"""Vía rápida: chat conversacional con Groq.

Para preguntas, resúmenes y skills ligeros. Prioriza latencia.
Mantiene un historial corto por usuario en memoria (fase 1;
en fase 2 pasa a la memoria persistente de dos niveles).
"""
from collections import defaultdict

from groq import AsyncGroq

from ..config import settings

_client: AsyncGroq | None = None
_historiales: dict[str, list[dict]] = defaultdict(list)
MAX_TURNOS = 10  # turnos de contexto que recordamos por usuario

PERSONALIDAD = """Eres Morgana, la asistente personal de {nombre}.
Eres directa, útil y con un punto de ironía. Respondes en el idioma
del usuario (normalmente español). Respuestas concisas: esto es un
chat, no un ensayo. Si el usuario pide algo sobre su código o sus
proyectos que requeriría un agente trabajando, dile que se lo
reformule como tarea (el router lo enviará al agente).
Cuando una respuesta dependa de información actual, noticias, precios,
versiones, normas, horarios o datos poco conocidos, usa la búsqueda web
integrada si está disponible. No busques para conversación general o hechos
estables. Si buscas, basa la respuesta en las fuentes recuperadas y conserva
las citas automáticas en el texto final."""


def client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


async def responder(user_id: str, nombre: str, mensaje: str) -> str:
    historial = _historiales[user_id]
    historial.append({"role": "user", "content": mensaje})

    messages = [
        {"role": "system", "content": PERSONALIDAD.format(nombre=nombre)},
        *historial[-MAX_TURNOS * 2:],
    ]
    modelo = (
        settings.groq_search_model
        if settings.groq_web_search_enabled
        else settings.groq_model
    )

    try:
        resp = await client().chat.completions.create(
            model=modelo,
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )
    except Exception:
        if not settings.groq_web_search_enabled:
            raise
        resp = await client().chat.completions.create(
            model=settings.groq_model,
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )
    texto = resp.choices[0].message.content
    historial.append({"role": "assistant", "content": texto})
    return texto

"""El router de Morgana.

Decide, para cada mensaje entrante, si va por la vía rápida (chat con
Groq, latencia mínima) o por la vía agéntica (tarea de código con
Claude, con plan + aprobación). El propio modelo rápido de Groq hace
de clasificador: es tan rápido que el peaje es invisible.
"""
import json
from typing import Literal, TypedDict

from groq import AsyncGroq

from .config import settings

_client: AsyncGroq | None = None


def client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


class Clasificacion(TypedDict):
    via: Literal["agentica", "rapida"]
    proyecto: str | None


PROMPT_CLASIFICADOR = """Eres el router de Morgana, un asistente personal.
Clasifica el mensaje del usuario en exactamente una de estas categorías:

- "agentica": el usuario pide trabajar sobre código o un proyecto — modificar,
  investigar, refactorizar, crear features, hacer planes de implementación,
  tocar un repositorio, ejecutar tests... Cualquier cosa que requiera un
  agente trabajando en un workspace.
- "rapida": todo lo demás — preguntas, conversación, resúmenes, traducciones,
  dudas conceptuales, cualquier cosa que se responda hablando.

Extrae además el nombre del proyecto si el usuario identifica uno. Devuelve solo
el nombre de la carpeta o proyecto, sin rutas ni explicaciones. Si no menciona
ninguno de forma explícita, usa null.

Responde SOLO con JSON válido y exactamente estas claves:
{"via": "agentica", "proyecto": "nombre-o-null"}

Ejemplos:
- "en morgana añade tests" -> {"via": "agentica", "proyecto": "morgana"}
- "revisa el proyecto pruebas" -> {"via": "agentica", "proyecto": "pruebas"}
- "refactoriza el login" -> {"via": "agentica", "proyecto": null}
- "qué es OAuth" -> {"via": "rapida", "proyecto": null}"""


async def clasificar(mensaje: str) -> Clasificacion:
    """Devuelve la vía y el proyecto mencionado, si lo hay.

    Ante la duda o error, cae en la vía rápida (barata y reversible).
    """
    try:
        resp = await client().chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": PROMPT_CLASIFICADOR},
                {"role": "user", "content": mensaje},
            ],
            temperature=0,
            max_tokens=80,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        via = data.get("via", "rapida")
        if via not in ("agentica", "rapida"):
            via = "rapida"

        proyecto = data.get("proyecto")
        if not isinstance(proyecto, str) or not proyecto.strip():
            proyecto = None
        else:
            proyecto = proyecto.strip()

        if via == "rapida":
            proyecto = None
        return {"via": via, "proyecto": proyecto}
    except Exception:
        return {"via": "rapida", "proyecto": None}

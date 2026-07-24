"""El router de Morgana.

Decide, para cada mensaje entrante, si va por la vía rápida (chat con
Groq, latencia mínima) o por la vía agéntica (tarea de código con
Claude, con plan + aprobación). El propio modelo rápido de Groq hace
de clasificador: es tan rápido que el peaje es invisible.
"""
import json
import re
import unicodedata
from typing import Literal, NotRequired, TypedDict

from groq import AsyncGroq

from .config import settings

_client: AsyncGroq | None = None


def client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


class Clasificacion(TypedDict):
    via: Literal["agentica", "rapida", "herramienta"]
    proyecto: str | None
    herramienta: NotRequired[str | None]
    argumentos: NotRequired[dict]


PROMPT_CLASIFICADOR = """Eres el router de Morgana, un asistente personal.
Clasifica el mensaje del usuario en exactamente una de estas categorías:

- "agentica": el usuario pide trabajar sobre código o un proyecto — modificar,
  investigar, refactorizar, crear features, hacer planes de implementación,
  tocar un repositorio, ejecutar tests... Cualquier cosa que requiera un
  agente trabajando en un workspace.
- "rapida": todo lo demás — preguntas, conversación, resúmenes, traducciones,
  dudas conceptuales, cualquier cosa que se responda hablando.
- "herramienta": el usuario pide localizar, buscar, descargar o pasar uno de
  sus archivos. Usa "files.search" con {"query": "texto a buscar"}.

Extrae además el nombre del proyecto si el usuario identifica uno. Devuelve solo
el nombre de la carpeta o proyecto, sin rutas ni explicaciones. Si no menciona
ninguno de forma explícita, usa null.

Responde SOLO con JSON válido y exactamente estas claves:
{"via": "agentica", "proyecto": "nombre-o-null", "herramienta": null, "argumentos": {}}

Ejemplos:
- "en morgana añade tests" -> {"via": "agentica", "proyecto": "morgana"}
- "revisa el proyecto pruebas" -> {"via": "agentica", "proyecto": "pruebas"}
- "refactoriza el login" -> {"via": "agentica", "proyecto": null}
- "pásame el archivo matrícula cuarto" -> {"via": "herramienta", "proyecto": null, "herramienta": "files.search", "argumentos": {"query": "matrícula cuarto"}}
- "qué es OAuth" -> {"via": "rapida", "proyecto": null}"""


def _normalizar(texto: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", texto.casefold())
        if not unicodedata.combining(character)
    )


def detectar_busqueda_archivo(mensaje: str) -> str | None:
    """Reconoce el flujo crítico aunque el clasificador remoto no responda."""
    normalizado = _normalizar(mensaje)
    acciones = ("busca", "buscame", "encuentra", "localiza", "pasame", "descarga")
    objetos = ("archivo", "documento", "pdf", "fichero")
    if not any(action in normalizado for action in acciones):
        return None
    if not any(objeto in normalizado for objeto in objetos):
        return None

    match = re.search(r"(?:se llama|llamado|llamada)\s+(.+)$", mensaje, re.IGNORECASE)
    if match:
        return match.group(1).strip(" .?\"") or None
    cleaned = re.sub(
        r"^.*?(?:busca(?:me)?|encuentra(?:me)?|localiza(?:me)?|p[aá]same|descarga)\s+",
        "",
        mensaje,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:el|la|un|una)?\s*(?:archivo|documento|pdf|fichero)?\s*(?:de|del|que)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" .?\"") or None


async def clasificar(mensaje: str) -> Clasificacion:
    """Devuelve la vía y el proyecto mencionado, si lo hay.

    Ante la duda o error, cae en la vía rápida (barata y reversible).
    """
    file_query = detectar_busqueda_archivo(mensaje)
    if file_query:
        return {
            "via": "herramienta",
            "proyecto": None,
            "herramienta": "files.search",
            "argumentos": {"query": file_query, "limit": 20},
        }
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
        if via not in ("agentica", "rapida", "herramienta"):
            via = "rapida"

        proyecto = data.get("proyecto")
        if not isinstance(proyecto, str) or not proyecto.strip():
            proyecto = None
        else:
            proyecto = proyecto.strip()

        herramienta = data.get("herramienta")
        argumentos = data.get("argumentos")
        if via == "herramienta":
            query = argumentos.get("query") if isinstance(argumentos, dict) else None
            if herramienta != "files.search" or not isinstance(query, str) or not query.strip():
                via = "rapida"
                herramienta = None
                argumentos = {}
            else:
                argumentos = {"query": query.strip(), "limit": 20}
        if via in ("rapida", "herramienta"):
            proyecto = None
        return {
            "via": via,
            "proyecto": proyecto,
            "herramienta": herramienta,
            "argumentos": argumentos if isinstance(argumentos, dict) else {},
        }
    except Exception:
        return {"via": "rapida", "proyecto": None}

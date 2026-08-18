"""El router de Vibi.

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

from . import ai_providers
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


PROMPT_CLASIFICADOR = """Eres el router de Vibi, un asistente personal.
Clasifica el mensaje del usuario en exactamente una de estas categorías:

- "agentica": el usuario pide trabajar sobre código o un proyecto — modificar,
  investigar, refactorizar, crear features, hacer planes de implementación,
  tocar un repositorio, ejecutar tests... Cualquier cosa que requiera un
  agente trabajando en un workspace.
- "rapida": todo lo demás — preguntas, conversación, resúmenes, traducciones,
  dudas conceptuales, cualquier cosa que se responda hablando.
- "herramienta": el usuario pide localizar, buscar, descargar, leer, resumir o
  explicar uno de sus archivos. Usa "files.search" para localizar o descargar y
  "files.read" cuando pide conocer, resumir o explicar su contenido. En `query`
  conserva la descripción contextual del archivo, no solo un supuesto nombre.

Extrae además el nombre del proyecto si el usuario identifica uno. Devuelve solo
el nombre de la carpeta o proyecto, sin rutas ni explicaciones. Si no menciona
ninguno de forma explícita, usa null.

Responde SOLO con JSON válido y exactamente estas claves:
{"via": "agentica", "proyecto": "nombre-o-null", "herramienta": null, "argumentos": {}}

Ejemplos:
- "en vibi añade tests" -> {"via": "agentica", "proyecto": "vibi"}
- "revisa el proyecto pruebas" -> {"via": "agentica", "proyecto": "pruebas"}
- "refactoriza el login" -> {"via": "agentica", "proyecto": null}
- "pásame el archivo matrícula cuarto" -> {"via": "herramienta", "proyecto": null, "herramienta": "files.search", "argumentos": {"query": "matrícula cuarto"}}
- "lee mi matrícula de cuarto de informática" -> {"via": "herramienta", "proyecto": null, "herramienta": "files.read", "argumentos": {"query": "matrícula cuarto informática"}}
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


def _ultimo_archivo_encontrado(historial: list[dict]) -> str | None:
    for message in reversed(historial):
        if message.get("role") != "assistant":
            continue
        match = re.search(
            r"He encontrado \d+ archivo\(s\): ([^,]+)",
            str(message.get("content") or ""),
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip().rstrip(".")
    return None


def detectar_lectura_archivo(
    mensaje: str, historial: list[dict] | None = None
) -> str | None:
    normalizado = _normalizar(mensaje)
    acciones = (
        "analiza",
        "contenido",
        "dime que pone",
        "explica",
        "lee",
        "leeme",
        "que dice",
        "que pone",
        "resume",
        "resumeme",
    )
    if not any(action in normalizado for action in acciones):
        return None
    objetos = ("archivo", "documento", "pdf", "fichero", "matricula")
    if any(objeto in normalizado for objeto in objetos):
        return mensaje.strip(" .?\"") or None
    if historial:
        return _ultimo_archivo_encontrado(historial)
    return None


def _json_response(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(clean[start : end + 1])


async def clasificar(
    mensaje: str,
    historial: list[dict] | None = None,
    user_id: str | None = None,
) -> Clasificacion:
    """Devuelve la vía y el proyecto mencionado, si lo hay.

    Ante la duda o error, cae en la vía rápida (barata y reversible).
    """
    read_query = detectar_lectura_archivo(mensaje, historial)
    detected_tool: Clasificacion | None = None
    if read_query:
        detected_tool = {
            "via": "herramienta",
            "proyecto": None,
            "herramienta": "files.read",
            "argumentos": {"query": read_query},
        }
    else:
        file_query = detectar_busqueda_archivo(mensaje)
        if file_query:
            detected_tool = {
                "via": "herramienta",
                "proyecto": None,
                "herramienta": "files.search",
                "argumentos": {"query": file_query, "limit": 20},
            }
    if detected_tool and not user_id:
        return detected_tool
    try:
        model_messages = [{"role": "system", "content": PROMPT_CLASIFICADOR}]
        model_messages.extend(
            {
                "role": str(item["role"]),
                "content": str(item["content"]),
            }
            for item in (historial or [])[-6:]
            if item.get("role") in {"user", "assistant"}
        )
        model_messages.append({"role": "user", "content": mensaje})
        if user_id:
            response_text = await ai_providers.complete_text(
                user_id,
                "tools",
                model_messages,
                temperature=0,
                max_tokens=180,
                json_mode=True,
            )
        else:
            resp = await client().chat.completions.create(
                model=settings.groq_model,
                messages=model_messages,
                temperature=0,
                max_tokens=180,
                response_format={"type": "json_object"},
                **ai_providers.opciones_groq(settings.groq_model),
            )
            response_text = resp.choices[0].message.content
        data = _json_response(response_text or "")
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
            if (
                herramienta not in {"files.search", "files.read"}
                or not isinstance(query, str)
                or not query.strip()
            ):
                via = "rapida"
                herramienta = None
                argumentos = {}
            else:
                argumentos = {"query": query.strip()}
                if herramienta == "files.search":
                    argumentos["limit"] = 20
        if via in ("rapida", "herramienta"):
            proyecto = None
        if via == "rapida" and detected_tool:
            return detected_tool
        return {
            "via": via,
            "proyecto": proyecto,
            "herramienta": herramienta,
            "argumentos": argumentos if isinstance(argumentos, dict) else {},
        }
    except Exception:
        return detected_tool or {"via": "rapida", "proyecto": None}

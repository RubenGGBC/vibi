"""La escena de cada usuario: su forma, su guardado y su difusión.

Una escena es un documento JSON pequeño. Las herramientas la editan siempre
igual, con `editar()`: se toma el candado del usuario, se trabaja sobre una
copia, y solo si la herramienta termina sin error se guarda, se sube la
versión y se manda a todas sus ventanas por el WebSocket. Una herramienta que
falla a la mitad no deja la escena a medias.

Forma (lo que recibe el cliente):

    {
      "version": 7,
      "titulo": "La serie armónica",
      "modo": "2d" | "3d",
      "ejes": {"visibles": true, "x": [0, 50], "y": [0, 5], "z": [-1, 1]},
      "parametros": [{"id": "N", "etiqueta": "Términos", "minimo": 1,
                      "maximo": 200, "paso": 1, "valor": 20}],
      "elementos": [{"id": "barras", "tipo": "sucesion", "etiqueta": "1/n",
                     "color": "#…", "procedencia": {...}, ...}],
      "pasos": [{"texto": "…", "idea": "…", "tarea": "…" | null,
                 "mostrar": [...], "ocultar": [...], "resaltar": [...],
                 "pregunta": {..., "pistas": [...]} | null}],
      "paso_actual": 0,
      "progreso": {"visto_hasta": 2, "respuestas": {"3": [0, 2]}}
    }

`progreso` es lo que ha hecho el alumno: hasta qué paso ha llegado y qué
opciones ha elegido en cada pregunta (por número de paso, en orden). Como el
paso actual, cambia sin subir la versión: no es editar la escena.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from ..config import settings
from .. import events
from .expresiones import CONSTANTES, FUNCIONES

MAX_ELEMENTOS = 40
MAX_PARAMETROS = 8
MAX_PASOS = 30
ID_VALIDO = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")

# Las variables de cada tipo de elemento: un deslizador no puede llamarse así.
VARIABLES_RESERVADAS = {"x", "y", "z", "n", "t"}

COLORES = {
    "azul": "#3b82f6",
    "rojo": "#ef4444",
    "verde": "#22c55e",
    "naranja": "#f97316",
    "morado": "#a855f7",
    "rosa": "#ec4899",
    "amarillo": "#eab308",
    "turquesa": "#14b8a6",
    "gris": "#94a3b8",
    "blanco": "#f8fafc",
}
PALETA = ["#3b82f6", "#f97316", "#22c55e", "#a855f7", "#ec4899", "#14b8a6", "#eab308", "#ef4444"]
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class EscenaError(ValueError):
    """Algo que el modelo tiene que corregir. El mensaje le dice qué."""


def escena_vacia() -> dict:
    return {
        "version": 0,
        "titulo": "",
        "modo": "2d",
        "ejes": {"visibles": True, "x": [-5.0, 5.0], "y": [-3.0, 3.0], "z": [-3.0, 3.0]},
        # El espacio libre donde viven los objetos compuestos (ancho, alto,
        # fondo), en las unidades que elija el agente: la cámara lo encuadra.
        "espacio": [10.0, 6.0, 6.0],
        "parametros": [],
        "elementos": [],
        "pasos": [],
        "paso_actual": 0,
        "progreso": {"visto_hasta": 0, "respuestas": {}},
        "actualizada_en": None,
    }


_escenas: dict[str, dict] = {}
_candados: dict[str, asyncio.Lock] = {}


def _ruta(user_id: str) -> Path:
    seguro = re.sub(r"[^A-Za-z0-9_-]", "_", user_id)[:80]
    return Path(settings.db_path).resolve().parent / "estudio" / "escenas" / f"{seguro}.json"


def cargar(user_id: str) -> dict:
    """La escena actual, de memoria o del disco. Nunca la original: una copia."""
    if user_id not in _escenas:
        ruta = _ruta(user_id)
        escena = escena_vacia()
        if ruta.is_file():
            try:
                guardada = json.loads(ruta.read_text(encoding="utf-8"))
                if isinstance(guardada, dict):
                    escena = {**escena, **guardada}
            except (OSError, json.JSONDecodeError):
                pass
        _escenas[user_id] = escena
    return copy.deepcopy(_escenas[user_id])


def _guardar(user_id: str, escena: dict) -> None:
    _escenas[user_id] = escena
    ruta = _ruta(user_id)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(escena, ensure_ascii=False), encoding="utf-8")
        temporal.replace(ruta)
    except OSError:
        # Sin disco la escena sigue viva en memoria: se pierde al reiniciar,
        # no a mitad de una explicación.
        pass


def olvidar_cache() -> None:
    """Para las pruebas: vuelve a leer del disco."""
    _escenas.clear()


async def difundir(user_id: str, escena: dict) -> None:
    await events.manager.send(user_id, {"tipo": "estudio_escena", "escena": escena})


@asynccontextmanager
async def editar(user_id: str) -> AsyncIterator[dict]:
    candado = _candados.setdefault(user_id, asyncio.Lock())
    async with candado:
        escena = cargar(user_id)
        yield escena
        escena["version"] = int(escena.get("version", 0)) + 1
        escena["actualizada_en"] = time.time()
        _guardar(user_id, escena)
    await difundir(user_id, copy.deepcopy(escena))


async def cambiar_paso(user_id: str, indice: int) -> dict:
    """Mover el paso no es editar la escena: no sube la versión y viaja solo."""
    candado = _candados.setdefault(user_id, asyncio.Lock())
    async with candado:
        escena = cargar(user_id)
        total = len(escena["pasos"])
        if total == 0:
            raise EscenaError("La escena no tiene pasos")
        if not 0 <= indice < total:
            raise EscenaError(f"El paso {indice + 1} no existe: hay {total}")
        escena["paso_actual"] = indice
        progreso = escena["progreso"]
        progreso["visto_hasta"] = max(int(progreso.get("visto_hasta", 0)), indice)
        _guardar(user_id, escena)
    await events.manager.send(user_id, {"tipo": "estudio_paso", "indice": indice})
    return escena


def estado_pregunta(pregunta: dict, elegidas: list[int]) -> dict:
    """Cómo va una pregunta. Misma regla que el cliente.

    Cada fallo destapa la pista siguiente; acertar, o fallar con las pistas
    ya gastadas, la cierra y enseña la explicación.
    """
    pistas = pregunta.get("pistas") or []
    acertada = pregunta["correcta"] in elegidas
    fallos = sum(1 for o in elegidas if o != pregunta["correcta"])
    resuelta = acertada or fallos > len(pistas)
    return {
        "acertada": acertada,
        "fallos": fallos,
        "resuelta": resuelta,
        "pista": pistas[fallos - 1] if fallos and not resuelta else None,
        "explicacion": pregunta["explicacion"] if resuelta else None,
    }


async def responder(user_id: str, indice: int, opcion: int) -> dict:
    """El alumno elige una opción en la pregunta de un paso."""
    candado = _candados.setdefault(user_id, asyncio.Lock())
    async with candado:
        escena = cargar(user_id)
        if not 0 <= indice < len(escena["pasos"]):
            raise EscenaError(f"El paso {indice + 1} no existe")
        pregunta = escena["pasos"][indice].get("pregunta")
        if not pregunta:
            raise EscenaError(f"El paso {indice + 1} no tiene pregunta")
        if not 0 <= opcion < len(pregunta["opciones"]):
            raise EscenaError("Esa opción no existe")
        respuestas = escena["progreso"]["respuestas"]
        elegidas = respuestas.get(str(indice + 1), [])
        if estado_pregunta(pregunta, elegidas)["resuelta"]:
            raise EscenaError("Esa pregunta ya está respondida")
        if opcion in elegidas:
            raise EscenaError("Esa opción ya la has probado")
        elegidas = [*elegidas, opcion]
        respuestas[str(indice + 1)] = elegidas
        _guardar(user_id, escena)
    await events.manager.send(
        user_id, {"tipo": "estudio_respuesta", "indice": indice, "elegidas": elegidas}
    )
    return {"elegidas": elegidas, **estado_pregunta(pregunta, elegidas)}


# --- Utilidades para las herramientas ----------------------------------------


def elemento(escena: dict, elemento_id: str) -> dict | None:
    return next((e for e in escena["elementos"] if e["id"] == elemento_id), None)


def ids_de_elementos(escena: dict) -> set[str]:
    return {e["id"] for e in escena["elementos"]}


def ids_de_parametros(escena: dict) -> set[str]:
    return {p["id"] for p in escena["parametros"]}


def valores_parametros(escena: dict) -> dict[str, float]:
    return {p["id"]: float(p["valor"]) for p in escena["parametros"]}


def resolver_id(escena: dict, tipo: str, pedido: str | None) -> str:
    """El id que pidió el modelo, o uno nuevo del estilo `funcion2`."""
    if pedido:
        if not ID_VALIDO.match(pedido):
            raise EscenaError(
                f"Id «{pedido}» no válido: letras, números y _, empezando por letra"
            )
        if pedido in ids_de_parametros(escena):
            raise EscenaError(f"«{pedido}» ya es el id de un deslizador")
        return pedido
    usados = ids_de_elementos(escena)
    numero = 1
    while f"{tipo}{numero}" in usados:
        numero += 1
    return f"{tipo}{numero}"


def resolver_color(escena: dict, pedido: str | None) -> str:
    if pedido:
        pedido = pedido.strip().lower()
        if pedido in COLORES:
            return COLORES[pedido]
        if HEX.match(pedido):
            return pedido
        raise EscenaError(
            f"Color «{pedido}» no válido: usa #rrggbb o uno de "
            f"{', '.join(COLORES)}"
        )
    usados = {e.get("color") for e in escena["elementos"]}
    libre = next((c for c in PALETA if c not in usados), None)
    return libre or PALETA[len(escena["elementos"]) % len(PALETA)]


def poner(escena: dict, nuevo: dict) -> bool:
    """Añade el elemento o sustituye al que tenga su id. ¿Sustituyó?"""
    for i, existente in enumerate(escena["elementos"]):
        if existente["id"] == nuevo["id"]:
            escena["elementos"][i] = nuevo
            return True
    if len(escena["elementos"]) >= MAX_ELEMENTOS:
        raise EscenaError(f"La escena ya tiene {MAX_ELEMENTOS} elementos")
    escena["elementos"].append(nuevo)
    return False


def variables_de_sistemas(escena: dict) -> dict[str, str]:
    """Cada variable de estado de un sistema dinámico → id del sistema."""
    return {
        variable: e["id"]
        for e in escena["elementos"]
        if e["tipo"] == "sistema"
        for variable in e["orden"]
    }


def nombres_vivos(escena: dict) -> set[str]:
    """Lo que puede aparecer en una fórmula que se evalúa cada fotograma:
    deslizadores, variables de sistemas y el tiempo."""
    return ids_de_parametros(escena) | set(variables_de_sistemas(escena)) | {"t"}


def validar_id_parametro(escena: dict, parametro_id: str) -> None:
    if not ID_VALIDO.match(parametro_id):
        raise EscenaError(f"Id de deslizador «{parametro_id}» no válido")
    if (
        parametro_id in VARIABLES_RESERVADAS
        or parametro_id in CONSTANTES
        or parametro_id in FUNCIONES
    ):
        raise EscenaError(
            f"«{parametro_id}» está reservado (variables x, y, z, n, t, "
            "constantes y funciones). Usa otro nombre, por ejemplo a, k o N"
        )
    if parametro_id in ids_de_elementos(escena):
        raise EscenaError(f"«{parametro_id}» ya es el id de un elemento")
    if parametro_id in variables_de_sistemas(escena):
        raise EscenaError(f"«{parametro_id}» ya es una variable de un sistema")


def referencias_de_paso(paso: dict) -> list[str]:
    """Los ids que nombra un paso. `elemento.parte` cuenta como `elemento`."""
    return [
        ref.split(".", 1)[0]
        for clave in ("mostrar", "ocultar", "resaltar")
        for ref in paso.get(clave, [])
    ]


def visibles_en(escena: dict, indice: int | None) -> set[str]:
    """Qué elementos se ven en ese paso. Misma regla que el cliente.

    Un elemento que se nombra por primera vez en un `mostrar` está oculto hasta
    ese paso; el resto se ve desde el principio. Cada paso aplica después sus
    `mostrar` y `ocultar` sobre lo que dejó el anterior.
    """
    ids = [e["id"] for e in escena["elementos"]]
    pasos = escena["pasos"]
    if not pasos or indice is None:
        return set(ids)
    primera: dict[str, str] = {}
    for paso in pasos:
        for clave in ("mostrar", "ocultar"):
            for ref in paso.get(clave, []):
                primera.setdefault(ref, clave)
    visibles = {i for i in ids if primera.get(i) != "mostrar"}
    for paso in pasos[: indice + 1]:
        visibles |= set(paso.get("mostrar", []))
        visibles -= set(paso.get("ocultar", []))
    return visibles & set(ids)

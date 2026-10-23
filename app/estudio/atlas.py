"""El atlas anatómico entero, bajo demanda.

No hay casos preparados: el índice (`atlas/indice.json`, ~3.900 piezas de
Z-Anatomy con su sistema y sus grupos) dice qué existe, y la geometría se
extrae al vuelo del `.blend` del atlas con Blender sin interfaz, en un
subproceso, cuando el agente la pide. El resultado se guarda en caché por la
lista de piezas: la segunda vez que alguien pide los riñones es instantáneo.

Que la pieza venga del atlas es lo que permite marcarla como verificada: el
agente elige qué enseñar, pero no puede inventarse una estructura que no esté
en el índice.
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import re
import tempfile
from functools import lru_cache
from pathlib import Path

from ..config import settings

INDICE = Path(__file__).resolve().parent / "atlas" / "indice.json"
EXPORTADOR = Path(__file__).resolve().parents[2] / "scripts" / "estudio_exportar_atlas.py"
MAX_PIEZAS = 400
MAX_VERTICES = 2_500_000
CLAVE = re.compile(r"^[0-9a-f]{20}$")


class AtlasError(ValueError):
    pass


@lru_cache(maxsize=1)
def indice() -> dict:
    datos = json.loads(INDICE.read_text(encoding="utf-8"))
    estructuras = datos["estructuras"]
    grupos: dict[str, list[str]] = {}
    for e in estructuras:
        for g in e["grupos"]:
            grupos.setdefault(g, []).append(e["nombre"])
        if e["sistema"]:
            grupos.setdefault(e["sistema"], []).append(e["nombre"])
    return {
        "fuente": datos["fuente"],
        "por_nombre": {e["nombre"]: e for e in estructuras},
        "por_minusculas": {e["nombre"].casefold(): e["nombre"] for e in estructuras},
        "grupos": grupos,
        "grupos_minusculas": {g.casefold(): g for g in grupos},
    }


def buscar(consulta: str, limite: int = 25) -> dict:
    """Piezas y grupos cuyo nombre contiene todas las palabras de la consulta."""
    datos = indice()
    palabras = [p for p in re.split(r"[\s,]+", consulta.casefold()) if p]
    if not palabras:
        raise AtlasError("Consulta vacía")

    def casa(texto: str) -> bool:
        texto = texto.casefold()
        return all(p in texto for p in palabras)

    def puntos(nombre: str) -> tuple:
        n = nombre.casefold()
        return (n != consulta.casefold(), not n.startswith(palabras[0]), len(n))

    piezas = sorted((n for n in datos["por_nombre"] if casa(n)), key=puntos)
    grupos = sorted((g for g in datos["grupos"] if casa(g)), key=puntos)
    resultado = {
        "piezas": [
            {
                "nombre": n,
                "sistema": datos["por_nombre"][n]["sistema"],
                "grupos": datos["por_nombre"][n]["grupos"],
            }
            for n in piezas[:limite]
        ],
        "total_piezas": len(piezas),
        "grupos": [{"nombre": g, "piezas": len(datos["grupos"][g])} for g in grupos[:10]],
    }
    if not piezas and not grupos:
        parecidas = difflib.get_close_matches(
            consulta.casefold(), list(datos["por_minusculas"]) + list(datos["grupos_minusculas"]),
            n=8, cutoff=0.5,
        )
        resultado["parecidas"] = [
            datos["por_minusculas"].get(p) or datos["grupos_minusculas"].get(p) for p in parecidas
        ]
    return resultado


def expandir(pedidas: list[str]) -> tuple[list[str], list[str]]:
    """Nombres de pieza o de grupo → piezas concretas. Devuelve las que no existen."""
    datos = indice()
    piezas: list[str] = []
    desconocidas: list[str] = []
    for pedida in pedidas:
        nombre = datos["por_minusculas"].get(pedida.casefold())
        grupo = datos["grupos_minusculas"].get(pedida.casefold())
        if nombre:
            nuevas = [nombre]
        elif grupo:
            nuevas = datos["grupos"][grupo]
        else:
            desconocidas.append(pedida)
            continue
        for n in nuevas:
            if n not in piezas:
                piezas.append(n)
    return piezas, desconocidas


def presupuesto(piezas: list[str]) -> int:
    datos = indice()
    return sum(datos["por_nombre"][n]["vertices"] for n in piezas)


def carpeta_cache() -> Path:
    return Path(settings.db_path).resolve().parent / "estudio" / "atlas"


def clave_de(piezas: list[str]) -> str:
    return hashlib.sha1("\n".join(sorted(piezas)).encode()).hexdigest()[:20]


def ruta_cache(clave: str) -> Path | None:
    if not CLAVE.match(clave):
        return None
    ruta = carpeta_cache() / f"{clave}.glb"
    return ruta if ruta.is_file() else None


def disponible() -> bool:
    return bool(
        settings.estudio_atlas_blend
        and settings.estudio_blender_python
        and Path(settings.estudio_atlas_blend).is_file()
        and Path(settings.estudio_blender_python).is_file()
    )


async def exportar(piezas: list[str]) -> str:
    """Extrae las piezas a un .glb (o lo encuentra en caché) y devuelve su clave."""
    clave = clave_de(piezas)
    if ruta_cache(clave):
        return clave
    if not disponible():
        raise AtlasError(
            "El atlas se puede buscar pero no cargar: falta configurar "
            "ESTUDIO_ATLAS_BLEND y ESTUDIO_BLENDER_PYTHON "
            "(scripts/estudio_preparar_atlas.sh). Dilo y no inventes la estructura"
        )
    carpeta = carpeta_cache()
    carpeta.mkdir(parents=True, exist_ok=True)
    salida = carpeta / f"{clave}.glb"
    temporal = carpeta / f"{clave}.tmp.glb"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as lista:
        json.dump(piezas, lista)
    try:
        proceso = await asyncio.create_subprocess_exec(
            settings.estudio_blender_python, str(EXPORTADOR), "--",
            settings.estudio_atlas_blend, lista.name, str(temporal),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            salida_proceso, _ = await asyncio.wait_for(
                proceso.communicate(), timeout=settings.estudio_atlas_timeout_seconds
            )
        except asyncio.TimeoutError as agotado:
            proceso.kill()
            raise AtlasError("Blender tardó demasiado en extraer las piezas") from agotado
        if proceso.returncode != 0 or not temporal.is_file():
            cola = salida_proceso.decode(errors="replace")[-400:]
            raise AtlasError(f"Blender no pudo extraer las piezas: {cola}")
        temporal.replace(salida)
    finally:
        Path(lista.name).unlink(missing_ok=True)
        temporal.unlink(missing_ok=True)
    return clave

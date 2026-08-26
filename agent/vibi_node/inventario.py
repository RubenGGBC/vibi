"""Un retrato del equipo que quepa en un párrafo.

La entrevista no debería preguntar lo que puede mirar: el catálogo de
aplicaciones dice poco —todo el mundo tiene un navegador— pero una carpeta
llamada `Farmacología II` con cuarenta PDF recientes dice el grado, el curso y
cómo estudia esa persona.

**Y lo que viaja es el agregado, no el contenido.** Aquí se cuentan carpetas y
extensiones y se manda eso: unos cientos de tokens. Ni un nombre de archivo ni
una línea de texto salen del equipo en este nivel. Abrir algo es el nivel 3 de
la escalada y exige permiso pedido en el momento.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from . import app_catalog

log = logging.getLogger("vibi.node.inventario")

# Cuántas carpetas se describen como mucho. Las que más archivos tienen son
# las que más dicen, y a partir de unas cuantas el retrato ya no mejora.
TOPE_CARPETAS = 25

# Y cuánto se baja. Dos niveles alcanzan `Documentos/Carrera/Farmacología`,
# que es donde vive la señal; más abajo empieza a costar y a repetir.
PROFUNDIDAD = 2

# Cuántas carpetas se visitan durante el descubrimiento. En un equipo con
# OneDrive sincronizado, node_modules o repos con miles de subcarpetas, un
# recorrido sin tope puede colgar la entrevista interactiva. Esta cota es
# generosa respecto a TOPE_CARPETAS porque el descubridor necesita ver más
# de lo que devolverá, para poder elegir el top N por volumen.
TOPE_ANCHURA = 500

# Presupuesto de tiempo en segundos. El recorrido corre en el equipo del
# usuario mientras espera una respuesta, así que necesita un freno de reloj.
# Dos segundos es razonable: un retrato incompleto es correcto y es la
# respuesta buena, y colgar la entrevista no.
PRESUPUESTO_INVENTARIO = 2.0

# Máxima longitud de una extensión. Cualquier texto tras el último punto de
# un nombre de archivo se cuenta como clave literal: sin sanear, un nombre
# como `informe.borrador-para-la-vista-del-juicio` filtraría eso entero como
# extensión. Solo se cuenta si es corta (máximo 8 chars) y alfanumérica.
MAX_SUFIJO = 8

_SUFIJO_VALIDO = re.compile(r"^[a-z0-9]+$")


def _dias_desde(momento: float) -> int:
    """Cuántos días hace que se tocó un archivo."""
    return max(0, int((time.time() - momento) / 86_400))


def _describir(carpeta: Path, raiz: Path) -> dict | None:
    """Lee una carpeta y devuelve sus extensiones, o None si está vacía o inaccesible."""
    extensiones: dict[str, int] = {}
    ultima = 0.0
    try:
        for hijo in carpeta.iterdir():
            if not hijo.is_file():
                continue
            sufijo = hijo.suffix.lower().lstrip(".")
            if not sufijo:
                continue
            # Solo contar si es corto (max 8 chars) y alfanumérico. Evita filtrar
            # texto libre desde nombres de archivo con sufijos descriptivos.
            if len(sufijo) > MAX_SUFIJO or not _SUFIJO_VALIDO.match(sufijo):
                continue
            extensiones[sufijo] = extensiones.get(sufijo, 0) + 1
            try:
                ultima = max(ultima, hijo.stat().st_mtime)
            except OSError:
                continue
    except (OSError, PermissionError):
        return None
    if not extensiones:
        return None
    # Ruta relativa a la raíz, conservando jerarquía pero sin exponer el
    # nombre de cuenta (`C:\Users\<usuario>\...`). Para la raíz misma, solo
    # su nombre de carpeta.
    try:
        ruta_relativa = str(carpeta.relative_to(raiz))
    except ValueError:
        # Si no es subpath (no debería pasar), usar solo el nombre.
        ruta_relativa = carpeta.name
    return {
        "ruta": ruta_relativa,
        "extensiones": dict(sorted(extensiones.items(), key=lambda p: -p[1])),
        "tocada_hace_dias": _dias_desde(ultima) if ultima else None,
    }


def _bajar(raiz: Path, profundidad: int, fin: float, contexto: dict) -> list[Path]:
    """Recorre los subdirectorios hasta la profundidad indicada.

    Respeta dos frenos: el presupuesto de tiempo (fin) y el tope de anchura
    (contexto['contador']). Vuelve en cuanto se agote cualquiera.
    """
    if profundidad <= 0 or time.monotonic() > fin:
        return []
    encontradas: list[Path] = []
    try:
        for hijo in raiz.iterdir():
            if hijo.is_dir() and not hijo.name.startswith("."):
                contexto['contador'] -= 1
                if contexto['contador'] <= 0:
                    return encontradas
                encontradas.append(hijo)
                if time.monotonic() > fin:
                    return encontradas
                encontradas.extend(_bajar(hijo, profundidad - 1, fin, contexto))
    except (OSError, PermissionError):
        return encontradas
    return encontradas


def mapa_de(raices: list[Path], tope_carpetas: int = TOPE_CARPETAS) -> dict:
    """Qué hay en estas carpetas, contado y sin nombres propios."""
    fin = time.monotonic() + PRESUPUESTO_INVENTARIO
    contexto = {'contador': TOPE_ANCHURA}

    # Mapeo carpeta -> raíz de la que descendió, para calcular rutas relativas.
    mapa_raices: dict[Path, Path] = {}

    for raiz in raices:
        if not raiz.exists() or time.monotonic() > fin:
            continue
        mapa_raices[raiz] = raiz
        for candidata in _bajar(raiz, PROFUNDIDAD, fin, contexto):
            mapa_raices[candidata] = raiz

    # Describir cada candidata usando su raíz de origen.
    descritas = [
        d for carpeta, raiz in mapa_raices.items()
        for d in [_describir(carpeta, raiz)] if d
    ]
    descritas.sort(key=lambda d: -sum(d["extensiones"].values()))

    # Recuperar aplicaciones. Si falla, devolver lista vacía sin abortar.
    apps = []
    try:
        aplicaciones = app_catalog.discover_windows_apps()
        apps = [app.label for app in aplicaciones[:60]]
    except Exception as err:
        log.debug(f"No se pudieron descubrir aplicaciones: {err}")

    return {"carpetas": descritas[:tope_carpetas], "apps": apps}

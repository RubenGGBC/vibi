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

import time
from pathlib import Path

# Cuántas carpetas se describen como mucho. Las que más archivos tienen son
# las que más dicen, y a partir de unas cuantas el retrato ya no mejora.
TOPE_CARPETAS = 25

# Y cuánto se baja. Dos niveles alcanzan `Documentos/Carrera/Farmacología`,
# que es donde vive la señal; más abajo empieza a costar y a repetir.
PROFUNDIDAD = 2


def _dias_desde(momento: float) -> int:
    """Cuántos días hace que se tocó un archivo."""
    return max(0, int((time.time() - momento) / 86_400))


def _describir(carpeta: Path) -> dict | None:
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
            extensiones[sufijo] = extensiones.get(sufijo, 0) + 1
            try:
                ultima = max(ultima, hijo.stat().st_mtime)
            except OSError:
                continue
    except (OSError, PermissionError):
        return None
    if not extensiones:
        return None
    return {
        "ruta": str(carpeta),
        "extensiones": dict(sorted(extensiones.items(), key=lambda p: -p[1])),
        "tocada_hace_dias": _dias_desde(ultima) if ultima else None,
    }


def _bajar(raiz: Path, profundidad: int) -> list[Path]:
    """Recorre los subdirectorios hasta la profundidad indicada."""
    if profundidad <= 0:
        return []
    encontradas: list[Path] = []
    try:
        for hijo in raiz.iterdir():
            if hijo.is_dir() and not hijo.name.startswith("."):
                encontradas.append(hijo)
                encontradas.extend(_bajar(hijo, profundidad - 1))
    except (OSError, PermissionError):
        return encontradas
    return encontradas


def mapa_de(raices: list[Path], tope_carpetas: int = TOPE_CARPETAS) -> dict:
    """Qué hay en estas carpetas, contado y sin nombres propios."""
    candidatas: list[Path] = []
    for raiz in raices:
        if not raiz.exists():
            continue
        candidatas.append(raiz)
        candidatas.extend(_bajar(raiz, PROFUNDIDAD))

    descritas = [d for d in (_describir(c) for c in candidatas) if d]
    descritas.sort(key=lambda d: -sum(d["extensiones"].values()))
    return {"carpetas": descritas[:tope_carpetas]}

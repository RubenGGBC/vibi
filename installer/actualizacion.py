"""Traerse la versión nueva de Vibi desde el repositorio.

La actualización es un `git pull` y poco más, pero las dos decisiones de
alrededor son las que la hacen usable: cuándo avisar de que hay algo nuevo, y
cuándo negarse porque hay trabajo sin guardar. Lo segundo importa más de lo que
parece — quien pulsa «actualizar» normalmente no sabe resolver un conflicto de
merge, y dejarle el árbol a medias es peor que no ofrecer el botón.

**Solo biblioteca estándar.**
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import deteccion

# Cuántos títulos de commit se traen para enseñar qué hay de nuevo. Suficiente
# para hacerse una idea; la lista entera no la lee nadie.
MAX_TITULOS = 10


class GitError(RuntimeError):
    """`git` no pudo con ello: sin red, sin remoto o sin repositorio."""


class HayTrabajoSinGuardar(RuntimeError):
    """El árbol tiene cambios propios y actualizar los pondría en peligro."""


@dataclass(frozen=True)
class Novedades:
    hay: bool = False
    commits: int = 0
    titulos: tuple[str, ...] = field(default_factory=tuple)
    problema: str = ""


def _git(
    args: list[str], raiz: Path | None = None, conservar_espacios: bool = False
) -> str:
    """Un `git` a secas, devolviendo su salida ya limpia.

    `conservar_espacios` existe por `status --porcelain`, donde la columna de
    estado son dos caracteres y el primero puede ser un espacio. Recortar la
    salida entera se lo come a la primera línea y solo a ella, así que el aviso
    de trabajo sin guardar decía «env.example» por «.env.example» y
    «gent/...» por «agent/...». Un fallo cosmético, pero de los que hacen dudar
    de si el programa entiende lo que está mirando.
    """
    destino = raiz or deteccion.raiz_del_repo()
    try:
        resultado = subprocess.run(
            ["git", *args],
            cwd=str(destino),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GitError(str(error)) from error
    if resultado.returncode != 0:
        raise GitError((resultado.stderr or resultado.stdout).strip())
    return resultado.stdout if conservar_espacios else resultado.stdout.strip()


def novedades() -> Novedades:
    """Qué hay en el remoto que aquí todavía no esté.

    Cuando falla —lo normal es no tener red— se devuelve «no hay», pero con el
    problema dentro. Las dos alternativas son peores: decir que estás al día
    esconde una actualización que existe, y decir que hay novedades ofrece un
    botón que va a fallar.
    """
    try:
        _git(["fetch", "--quiet"])
        cuenta = _git(["rev-list", "--count", "HEAD..@{u}"])
        pendientes = int(cuenta or "0")
        if not pendientes:
            return Novedades(hay=False)
        titulos = _git(
            ["log", "--pretty=%s", f"-{MAX_TITULOS}", "HEAD..@{u}"]
        ).splitlines()
        return Novedades(
            hay=True,
            commits=pendientes,
            titulos=tuple(t.strip() for t in titulos if t.strip()),
        )
    except (GitError, ValueError) as error:
        return Novedades(hay=False, problema=str(error))


def _cambios_propios() -> list[str]:
    """Lo que el usuario tiene tocado y sin guardar.

    Los archivos sin seguimiento (`??`) no cuentan: `data/`, el `.env` y los
    logs salen ahí siempre y no estorban a un `pull`. Lo que bloquea es lo
    modificado sobre archivos que el repositorio sí controla, porque es
    exactamente lo que puede acabar en conflicto.
    """
    salida = _git(["status", "--porcelain"], conservar_espacios=True)
    return [
        linea
        for linea in salida.splitlines()
        if linea.strip() and not linea.startswith("??")
    ]


def actualizar() -> Novedades:
    """Trae la versión nueva. No toca nada si hay trabajo sin guardar."""
    pendientes = _cambios_propios()
    if pendientes:
        raise HayTrabajoSinGuardar(
            "Tienes cambios sin guardar en "
            + ", ".join(linea[3:] for linea in pendientes[:5])
            + ". Guárdalos o descártalos y vuelve a intentarlo."
        )
    _git(["pull", "--ff-only"])
    return novedades()

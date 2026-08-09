"""Qué parte del disco ven las herramientas de archivos de este nodo.

La raíz es la máquina entera: el sentido de esto es que Morgana pueda abrir la
carpeta de Descargas, un repo cualquiera o un documento sin que nadie haya
tenido que declararlo antes. Lo que queda fuera es una lista corta de sitios
donde vive material que Morgana no necesita para nada y que una lectura
descuidada volcaría en el contexto: claves, tokens y logins.

**Esto no es una frontera de seguridad, y conviene no confundirse.** El
intérprete de comandos de este mismo nodo llega a todos esos sitios desde el 5
de agosto —`shell.run` es bash libre, decidido a propósito—, así que filtrar las
herramientas de archivos no impide nada que el shell no permita ya. Lo que hace
es evitar el accidente: que un «busca en mi carpeta personal» arrastre la clave
privada de SSH a una conversación. Quien quiera moverla la mueve; la lista está
para que no pase sin querer.

Por eso `system_shell` no consulta este módulo. Que lo hiciera sería teatro, y
el teatro en seguridad es peor que la ausencia: se confía en él.
"""
from __future__ import annotations

import fnmatch
import os
from functools import lru_cache
from pathlib import Path

# Con qué añadir sitios a la lista, separados por el separador de rutas del
# sistema (`;` en Windows, `:` fuera). Acepta rutas y patrones de nombre.
VARIABLE_EXCLUIR = "MORGANA_FS_EXCLUIR"

# Carpetas donde vive el material sensible, relativas a la carpeta personal.
CARPETAS_EXCLUIDAS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".gemini",       # el login de la CLI de Antigravity, en claro
    ".claude",       # y el de Claude Code
    ".morgana",      # el token de este nodo
    ".config/gh",
    ".docker",
    "AppData/Roaming/Microsoft/Crypto",
    "AppData/Local/Microsoft/Credentials",
)

# Nombres que son secretos vayan donde vayan. `.env` es el caso que más veces se
# cruza en el camino: está en la raíz de casi todos los proyectos del usuario.
PATRONES_EXCLUIDOS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    ".netrc",
    "credentials.json",
)


class FueraDeAlcance(Exception):
    """La ruta existe pero Morgana no la mira."""


def _declaradas() -> tuple[str, ...]:
    crudo = os.environ.get(VARIABLE_EXCLUIR, "").strip()
    if not crudo:
        return ()
    return tuple(parte.strip() for parte in crudo.split(os.pathsep) if parte.strip())


@lru_cache(maxsize=8)
def _resolver_excluidas(declaradas: tuple[str, ...], casa: str) -> tuple[Path, ...]:
    """La parte cara, hecha una vez.

    Esto se consulta por archivo mientras se recorre un árbol, y resolver una
    docena de rutas en cada uno son cientos de miles de llamadas al sistema en
    una búsqueda grande. Los argumentos son lo único de lo que depende el
    resultado, así que la caché no puede quedarse vieja sin que se note.
    """
    raiz = Path(casa)
    crudas = [raiz / relativa for relativa in CARPETAS_EXCLUIDAS]
    crudas += [
        Path(declarada).expanduser()
        for declarada in declaradas
        if os.sep in declarada or (os.altsep and os.altsep in declarada)
    ]

    resueltas: list[Path] = []
    for carpeta in crudas:
        try:
            resueltas.append(carpeta.resolve())
        except OSError:
            continue  # una ruta que el sistema no sabe resolver no veta nada
    return tuple(resueltas)


def carpetas_excluidas() -> tuple[Path, ...]:
    """Las carpetas vetadas, ya resueltas y en absoluto.

    Se resuelven los enlaces aquí y no al comparar porque el veto tiene que
    valer para el destino: en Windows es normal que `AppData` esté redirigido, y
    comparando las cadenas tal cual la carpeta redirigida quedaría dentro.
    """
    return _resolver_excluidas(_declaradas(), str(Path.home()))


def patrones_excluidos() -> tuple[str, ...]:
    sueltos = tuple(
        declarada
        for declarada in _declaradas()
        if os.sep not in declarada and not (os.altsep and os.altsep in declarada)
    )
    return PATRONES_EXCLUIDOS + sueltos


def _resolver(ruta: Path) -> Path:
    """La ruta con los enlaces deshechos, exista o no todavía.

    `strict=False` es lo que permite comprobar el destino de un archivo que se
    va a crear: se resuelve la parte que ya existe y el resto se añade tal cual.
    """
    try:
        return ruta.resolve()
    except OSError:
        return ruta.absolute()


def permitida(ruta: Path) -> bool:
    resuelta = _resolver(ruta)

    nombre = resuelta.name
    for patron in patrones_excluidos():
        if fnmatch.fnmatch(nombre, patron):
            return False

    for carpeta in carpetas_excluidas():
        # `is_relative_to` cubre la carpeta y todo lo que cuelgue de ella. Y
        # comparando rutas resueltas, un enlace que apunte dentro tampoco entra:
        # su destino sí es relativo a la carpeta vetada aunque el enlace viva en
        # el escritorio.
        if resuelta == carpeta or resuelta.is_relative_to(carpeta):
            return False

    return True


def resolver(cruda: object, base: Path | None = None) -> Path:
    """Convierte lo que llegue en una ruta absoluta que se pueda tocar.

    Una ruta relativa se entiende contra `base` —la carpeta de trabajo que haya
    dicho el modelo, o la personal si no dijo ninguna—. Devolver siempre
    absoluto importa porque quien pregunta está en otra máquina y no comparte
    nuestro directorio actual.
    """
    texto = str(cruda or "").strip()
    if not texto:
        raise FueraDeAlcance("No has dicho qué ruta")

    ruta = Path(texto).expanduser()
    if not ruta.is_absolute():
        ruta = (base or Path.home()) / ruta

    resuelta = _resolver(ruta)
    if not permitida(resuelta):
        raise FueraDeAlcance(
            f"«{resuelta}» está en la lista de sitios que Morgana no abre "
            f"(claves, tokens y logins). Si de verdad hace falta, dilo y se "
            f"saca de {VARIABLE_EXCLUIR}."
        )
    return resuelta

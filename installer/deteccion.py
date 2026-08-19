"""Qué hay en esta máquina y qué se le puede ofrecer al usuario.

Este módulo solo mira y decide; instalar es cosa de `acciones`. La separación
importa porque de aquí sale lo que el asistente enseña por pantalla, y esa
pantalla tiene que poder pintarse antes de tocar nada.

**Solo biblioteca estándar, y es obligatorio**: esto corre antes de crear el
entorno y de instalar una sola dependencia. Cualquier import de fuera rompería
el instalador justo en la máquina donde más falta hace.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Por debajo de esto no arranca: el código usa sintaxis de 3.11 (`X | None` en
# anotaciones evaluadas, `tomllib`, grupos de excepciones) y descubrirlo a
# mitad de la instalación deja el sistema a medio hacer.
PYTHON_MINIMO = (3, 11)

# Los nombres con los que cada sistema se presenta, traducidos a los que
# usamos por dentro. `platform.system()` devuelve «Darwin» para macOS, que no
# es lo que nadie espera leer en una pantalla.
SISTEMAS = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}


@dataclass(frozen=True)
class Requisito:
    """Algo que tiene que estar en la máquina para que Vibi funcione.

    `imprescindible` separa lo que bloquea la instalación de lo que solo la
    recorta. Sin `agy` no hay motor; sin `npx` te quedas sin navegador, que es
    una capacidad menos, no un fracaso.

    Y `lo_instalo_yo` es lo que evita que «imprescindible» signifique «vete a
    buscarlo tú»: si el instalador sabe traerlo, la pantalla lo dice y sigue
    adelante en vez de plantarse. Solo bloquea lo que falta Y no sabemos
    conseguir.
    """

    clave: str
    nombre: str
    encontrado: bool
    detalle: str
    imprescindible: bool
    como_conseguirlo: str
    lo_instalo_yo: bool = False


@dataclass(frozen=True)
class Capacidad:
    """Algo que Vibi sabrá hacer, dicho como lo diría el usuario.

    `explicacion` no es documentación: es lo que se lee al lado de la casilla
    para decidir si la quieres. Y `motivo` existe porque una casilla apagada
    sin explicación parece un fallo del instalador.
    """

    clave: str
    nombre: str
    explicacion: str
    disponible: bool
    motivo: str = ""
    recomendada: bool = True


def sistema_operativo() -> str:
    """Cuál de los tres, o «desconocido».

    No se adivina: de esto dependen las capacidades que se ofrecen, y tratar un
    sistema raro como si fuera Linux le prometería al usuario cosas que no van
    a funcionar en su máquina.
    """
    return SISTEMAS.get(platform.system(), "desconocido")


# A partir de esta compilación, Windows 10 pasó a llamarse Windows 11. Python
# no se enteró: `platform.release()` sigue devolviendo «10» en las dos, y el
# número real está en `platform.version()`.
BUILD_WINDOWS_11 = 22000


def _version_de_windows() -> str:
    """«10» u «11», leído de la compilación en vez de creerse a Python.

    Suena a detalle y no lo es: esto es la primera frase que lee el usuario
    —«va a vivir en tu Windows 10»— y equivocarse ahí le hace dudar de todo lo
    que el instalador diga después.
    """
    try:
        build = int(platform.version().split(".")[2])
    except (IndexError, ValueError):
        return platform.release() or ""
    return "11" if build >= BUILD_WINDOWS_11 else "10"


def descripcion_del_sistema() -> str:
    """Cómo llamarlo por pantalla, con su versión."""
    so = sistema_operativo()
    nombres = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}
    bonito = nombres.get(so, platform.system() or "este sistema")
    version = _version_de_windows() if so == "windows" else (platform.release() or "")
    return f"{bonito} {version}".strip()


def requisito_python() -> Requisito:
    version = ".".join(str(n) for n in sys.version_info[:3])
    vale = tuple(sys.version_info[:2]) >= PYTHON_MINIMO
    minimo = ".".join(str(n) for n in PYTHON_MINIMO)
    return Requisito(
        clave="python",
        nombre="Python",
        encontrado=vale,
        detalle=version,
        imprescindible=True,
        como_conseguirlo=(
            ""
            if vale
            else f"Vibi necesita Python {minimo} o posterior; tienes {version}. "
            "Instálalo desde python.org y vuelve a lanzar el instalador con él."
        ),
    )


def _version_de(comando: list[str]) -> str:
    """La primera línea que suelte el programa, o vacío si no contesta.

    Muchas CLI escriben su versión por stderr (`agy --help` entre ellas), así
    que se juntan las dos salidas en vez de mirar solo stdout.
    """
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    salida = f"{resultado.stdout}\n{resultado.stderr}".strip()
    return salida.splitlines()[0].strip() if salida else ""


def _ruta_de(programa: str) -> str:
    return shutil.which(programa) or ""


def requisito_agy() -> Requisito:
    """La CLI de Antigravity, que es el motor.

    Se instala sola: Google publica un guion por sistema y el instalador lo
    ejecuta (ver `installer.agy`). Lo que NO se puede automatizar es el login,
    que abre OAuth y exige un terminal de verdad
    (`bubbletea: could not open TTY`); de eso avisa el último paso.
    """
    from . import agy  # noqa: PLC0415 - perezoso, para no cerrar un ciclo

    ruta = agy.donde_esta()
    so = sistema_operativo()
    sabemos_traerla = so in ("windows", "macos", "linux")
    return Requisito(
        clave="agy",
        nombre="Antigravity",
        encontrado=bool(ruta),
        detalle=ruta,
        imprescindible=True,
        lo_instalo_yo=sabemos_traerla,
        como_conseguirlo=(
            ""
            if ruta
            else "La instalo yo en un momento."
            if sabemos_traerla
            else "Antigravity solo existe para Windows, macOS y Linux."
        ),
    )


def requisito_git() -> Requisito:
    ruta = _ruta_de("git")
    return Requisito(
        clave="git",
        nombre="Git",
        encontrado=bool(ruta),
        detalle=_version_de(["git", "--version"]) if ruta else "",
        imprescindible=False,
        como_conseguirlo=(
            ""
            if ruta
            else "Sin Git, Vibi funciona pero no podrá actualizarse sola. "
            "Instálalo desde git-scm.com."
        ),
    )


def _npx_del_env() -> str:
    """Lo que el `.env` diga de `npx`, si es que ya había uno."""
    ruta = raiz_del_repo() / ".env"
    try:
        crudo = ruta.read_text(encoding="utf-8")
    except OSError:
        return ""
    for linea in crudo.splitlines():
        limpia = linea.strip()
        if limpia.startswith(("VIBI_NPX=", "MORGANA_NPX=")):
            valor = limpia.partition("=")[2].strip()
            if valor and Path(valor).exists():
                return valor
    return ""


def requisito_npx() -> Requisito:
    """Node trae `npx`, y `npx` es quien levanta el navegador de Playwright."""
    # Tres sitios, y hacen falta los tres: el PATH; la variable, que es como se
    # le dice a Vibi dónde está cuando no lo está; y el `.env`, porque quien ya
    # tenía Vibi funcionando la puso ahí y no en el entorno de esta consola.
    # Con nvm es lo normal que falle el PATH: la versión activa puede no traer
    # `npx` aunque haya otra instalada que sí.
    ruta = (
        _ruta_de("npx")
        or os.environ.get("VIBI_NPX", "")
        or os.environ.get("MORGANA_NPX", "")
        or _npx_del_env()
    )
    return Requisito(
        clave="npx",
        nombre="Node",
        encontrado=bool(ruta),
        detalle=ruta,
        imprescindible=False,
        como_conseguirlo=(
            ""
            if ruta
            else "Sin Node, Vibi no puede navegar por ti. Instálalo desde "
            "nodejs.org; el resto funciona igual."
        ),
    )


def requisitos() -> tuple[Requisito, ...]:
    """Todo lo que se comprueba, en el orden en que se enseña."""
    return (
        requisito_python(),
        requisito_agy(),
        requisito_git(),
        requisito_npx(),
    )


def se_puede_instalar(lista: tuple[Requisito, ...]) -> bool:
    """Solo bloquea lo que falta Y no sabemos traer.

    Lo opcional recorta capacidades pero no impide nada, y lo imprescindible
    que el instalador sepa instalar tampoco: para eso está.
    """
    return all(
        r.encontrado or r.lo_instalo_yo for r in lista if r.imprescindible
    )


def capacidades(so: str) -> tuple[Capacidad, ...]:
    """Qué sabrá hacer Vibi en esta máquina, y qué no y por qué.

    El corte no es caprichoso: el agente de nodo lee la pantalla, mueve el ratón
    y escucha las notificaciones con código escrito contra las API de Windows
    (`ui_windows`, `mouse_windows`, `notifications_windows`). En macOS y Linux
    esos módulos no tienen equivalente todavía, así que la capacidad se enseña
    apagada y con el motivo delante. Ofrecerla igual sería peor que no
    ofrecerla: el usuario la activaría y fallaría el día que la necesita.
    """
    solo_windows = (
        "Por ahora solo en Windows: está escrito contra sus APIs y todavía no "
        "tiene equivalente aquí."
    )
    es_windows = so == "windows"
    return (
        Capacidad(
            clave="chat",
            nombre="Conversación",
            explicacion=(
                "Hablar con Vibi por texto y por voz, con su memoria de la "
                "conversación. Es el corazón: sin esto no hay Vibi."
            ),
            disponible=True,
        ),
        Capacidad(
            clave="terminal",
            nombre="Tu disco y tu terminal",
            explicacion=(
                "Leer, escribir y buscar en tus archivos, y ejecutar comandos. "
                "Vibi corre en tu ordenador, así que son los tuyos de verdad."
            ),
            disponible=True,
        ),
        Capacidad(
            clave="malla",
            nombre="Varios dispositivos",
            explicacion=(
                "Conectar tus otras máquinas y mandarles órdenes o archivos "
                "desde aquí, aunque estén en otro sitio."
            ),
            disponible=True,
        ),
        Capacidad(
            clave="navegador",
            nombre="Navegar por ti",
            explicacion=(
                "Abrir páginas en tu navegador, con tus sesiones ya iniciadas, "
                "y trabajar dentro de ellas mientras lo ves en tu pantalla."
            ),
            disponible=requisito_npx().encontrado,
            motivo=(
                ""
                if requisito_npx().encontrado
                else "Necesita Node instalado para levantar el servidor."
            ),
        ),
        Capacidad(
            clave="escritorio",
            nombre="Tu ratón y tu teclado",
            explicacion=(
                "Manejar aplicaciones que no tienen otra puerta: leer la ventana, "
                "pulsar botones y escribir por ti."
            ),
            disponible=es_windows,
            motivo="" if es_windows else solo_windows,
        ),
        Capacidad(
            clave="notificaciones",
            nombre="Avisarte de lo que pasa",
            explicacion=(
                "Leer las notificaciones del sistema y contarte en voz alta "
                "solo lo que te importa."
            ),
            disponible=es_windows,
            motivo="" if es_windows else solo_windows,
            recomendada=False,
        ),
        Capacidad(
            clave="wake_word",
            nombre="Responder a su nombre",
            explicacion=(
                "Escuchar en segundo plano y despertarse cuando dices «Vibi», "
                "sin tocar nada. El audio no sale de tu ordenador."
            ),
            disponible=es_windows,
            motivo="" if es_windows else solo_windows,
            recomendada=False,
        ),
    )


def raiz_del_repo() -> Path:
    """La carpeta del repo, deducida de dónde vive este archivo."""
    return Path(__file__).resolve().parents[1]

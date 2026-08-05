"""Lo que este nodo sabe hacer.

El agente solo ejecuta capacidades de este diccionario. `shell.run` es la
excepción deliberada: abre un intérprete de comandos completo, y con él este
archivo deja de ser la frontera de seguridad. La frontera pasa a estar en el
servidor (que decide qué se ejecuta solo y qué te pregunta antes) y en los
privilegios del usuario del sistema bajo el que corre este proceso.

Nada de lo que hay aquí filtra comandos por su contenido: bash es un lenguaje
completo y cualquier lista negra se evade con `echo ... | sh`. Lo que sí hay
son límites de recursos —tiempo, tamaño de salida— para que una orden mal
formada no deje la máquina colgada ni llene la base de datos.
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from . import media
from .config import NodeConfig

MAX_PROJECTS = 200
MAX_RESULTADOS_BUSQUEDA = 100

# Un comando que tarda más que esto casi nunca es lo que querías: o se ha
# quedado esperando entrada por stdin o se ha colgado. El nodo lo mata y te
# devuelve lo que hubiera escrito hasta ese momento.
SHELL_TIMEOUT_DEFAULT = 60
SHELL_TIMEOUT_MAX = 600

# El servidor rechaza resultados enormes (MAX_RESULT_BYTES). Cortamos antes
# aquí para no mandar por el cable algo que se va a descartar al llegar.
MAX_SALIDA_CHARS = 60_000

ESQUEMAS_URL = ("http", "https")


class CapabilityError(Exception):
    pass


def _ping(config: NodeConfig, _: dict) -> dict:
    return {
        "hostname": socket.gethostname(),
        "plataforma": f"{platform.system()} {platform.release()}",
        "nodo": config.nombre,
        "hora": time.time(),
    }


def _list_projects(config: NodeConfig, _: dict) -> dict:
    root = Path(config.projects_root).expanduser()
    if not root.is_dir():
        raise CapabilityError(
            f"La carpeta de proyectos configurada no existe: {root}"
        )

    proyectos = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        proyectos.append(
            {
                "nombre": entry.name,
                "git": (entry / ".git").exists(),
                "modificado_en": entry.stat().st_mtime,
            }
        )
        if len(proyectos) >= MAX_PROJECTS:
            break

    # La ruta absoluta se queda en la máquina: al servidor solo van nombres.
    return {"proyectos": proyectos, "total": len(proyectos)}


# ---------- Shell ----------

def _truncar(texto: str) -> tuple[str, bool]:
    if len(texto) <= MAX_SALIDA_CHARS:
        return texto, False
    # La cola suele importar más que la cabeza: el error final está al final.
    return texto[-MAX_SALIDA_CHARS:], True


def _directorio_trabajo(config: NodeConfig, pedido: object) -> Path:
    if not pedido:
        return Path.home()
    directorio = Path(str(pedido)).expanduser()
    if not directorio.is_absolute():
        directorio = Path(config.projects_root).expanduser() / directorio
    if not directorio.is_dir():
        raise CapabilityError(f"El directorio no existe: {directorio}")
    return directorio


def _shell_run(config: NodeConfig, arguments: dict) -> dict:
    comando = str(arguments.get("comando") or "").strip()
    if not comando:
        raise CapabilityError("No has dicho qué comando ejecutar")

    try:
        timeout = int(arguments.get("timeout") or SHELL_TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        raise CapabilityError("El timeout tiene que ser un número de segundos")
    timeout = max(1, min(timeout, SHELL_TIMEOUT_MAX))

    directorio = _directorio_trabajo(config, arguments.get("directorio"))

    # stdin cerrado a propósito: un comando que pregunte algo interactivamente
    # debe fallar al instante, no consumir el timeout entero esperando a nadie.
    try:
        completado = subprocess.run(
            comando,
            shell=True,
            cwd=str(directorio),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as expirado:
        parcial = expirado.stdout if isinstance(expirado.stdout, str) else ""
        aviso = f"El comando seguía corriendo tras {timeout}s y se ha cortado."
        if parcial.strip():
            aviso += f" Salida parcial: {parcial[-2000:]}"
        raise CapabilityError(aviso) from expirado

    stdout, stdout_cortado = _truncar(completado.stdout or "")
    stderr, stderr_cortado = _truncar(completado.stderr or "")
    return {
        "codigo": completado.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncado": stdout_cortado or stderr_cortado,
        "directorio": str(directorio),
    }


# ---------- Escritorio ----------

def _abrir_en_escritorio(objetivo: str) -> None:
    """Entrega algo al escritorio para que lo abra con su aplicación normal.

    Cada sistema tiene su propio verbo. En Windows `start` es una palabra del
    intérprete, no un programa, así que hay que invocarlo a través de él.
    """
    sistema = platform.system()
    if sistema == "Darwin":
        subprocess.Popen(["open", objetivo], stdin=subprocess.DEVNULL)
    elif sistema == "Windows":
        os.startfile(objetivo)  # noqa: S606 - es la vía nativa en Windows
    else:
        lanzador = shutil.which("xdg-open")
        if lanzador is None:
            raise CapabilityError(
                "No encuentro xdg-open: este escritorio no sabe abrir enlaces"
            )
        subprocess.Popen([lanzador, objetivo], stdin=subprocess.DEVNULL)


def _browser_open(_: NodeConfig, arguments: dict) -> dict:
    url = str(arguments.get("url") or "").strip()
    if not url:
        raise CapabilityError("No has dicho qué URL abrir")

    partes = urlparse(url)
    # Sin esto, una «url» como file:///... o javascript:... convierte esta
    # capacidad en algo bastante más amplio de lo que su nombre promete.
    if partes.scheme not in ESQUEMAS_URL or not partes.netloc:
        raise CapabilityError(
            f"Solo abro direcciones http o https, y esto no lo es: {url[:120]}"
        )

    _abrir_en_escritorio(url)
    return {"abierto": url, "nodo": platform.system()}


def _open_path(config: NodeConfig, arguments: dict) -> dict:
    crudo = str(arguments.get("ruta") or "").strip()
    if not crudo:
        raise CapabilityError("No has dicho qué archivo abrir")

    ruta = Path(crudo).expanduser()
    if not ruta.is_absolute():
        ruta = Path(config.projects_root).expanduser() / ruta
    if not ruta.exists():
        raise CapabilityError(f"No existe: {ruta}")

    _abrir_en_escritorio(str(ruta))
    return {"abierto": str(ruta)}


# ---------- Archivos ----------

def _files_search(config: NodeConfig, arguments: dict) -> dict:
    patron = str(arguments.get("patron") or "").strip()
    if not patron:
        raise CapabilityError("No has dicho qué buscar")

    raiz_pedida = arguments.get("directorio")
    raiz = (
        Path(str(raiz_pedida)).expanduser()
        if raiz_pedida
        else Path(config.projects_root).expanduser()
    )
    if not raiz.is_dir():
        raise CapabilityError(f"El directorio no existe: {raiz}")

    encontrados = []
    for ruta in raiz.rglob(patron):
        try:
            info = ruta.stat()
        except OSError:
            continue
        encontrados.append(
            {
                "ruta": str(ruta),
                "nombre": ruta.name,
                "directorio": ruta.is_dir(),
                "bytes": info.st_size if ruta.is_file() else None,
                "modificado_en": info.st_mtime,
            }
        )
        if len(encontrados) >= MAX_RESULTADOS_BUSQUEDA:
            break

    return {
        "resultados": encontrados,
        "total": len(encontrados),
        "truncado": len(encontrados) >= MAX_RESULTADOS_BUSQUEDA,
        "raiz": str(raiz),
    }


# ---------- Reproducción ----------

def _media_control(_: NodeConfig, arguments: dict) -> dict:
    accion = str(arguments.get("accion") or "").strip().lower()
    titulo = str(arguments.get("titulo") or "").strip() or None
    # La espera solo tiene sentido persiguiendo un título concreto: sin él no
    # hay nada que esperar y bloquear el nodo doce segundos sería absurdo.
    espera = float(arguments.get("espera") or 0.0) if titulo else 0.0
    try:
        return media.control(accion, titulo, min(espera, media.ESPERA_SESION))
    except media.MediaError as error:
        raise CapabilityError(str(error)) from error


def _media_now_playing(_: NodeConfig, __: dict) -> dict:
    try:
        return media.now_playing()
    except media.MediaError as error:
        raise CapabilityError(str(error)) from error


HANDLERS = {
    "ping": _ping,
    "projects.list": _list_projects,
    "shell.run": _shell_run,
    "browser.open": _browser_open,
    "open.path": _open_path,
    "files.search": _files_search,
    "media.control": _media_control,
    "media.now_playing": _media_now_playing,
}


def run(config: NodeConfig, capability: str, arguments: dict) -> dict:
    handler = HANDLERS.get(capability)
    if handler is None:
        raise CapabilityError(f"Este dispositivo no sabe hacer «{capability}»")
    return handler(config, arguments or {})

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

import httpx

from . import browser_mcp, media, system_mcp
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

# Una transferencia puede durar lo que dure: un vídeo de varios gigas por una
# subida doméstica se va a la hora larga. Lo que sí tiene tope es plantarse ante
# un servidor que no contesta al conectar.
TIMEOUT_TRANSFERENCIA = httpx.Timeout(30.0, read=None, write=None, pool=None)


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


def _browser_mcp(_: NodeConfig, arguments: dict) -> dict:
    """Enciende, apaga o consulta el servidor con el que Morgana navega aquí.

    El navegador tiene que abrirse en esta máquina —es lo que da sentido a la
    capacidad: que el usuario vea lo que se está haciendo—, así que el servidor
    de Playwright vive aquí y `agy` se conecta a él desde donde esté.
    """
    accion = str(arguments.get("accion") or "arrancar").strip().lower()

    try:
        puerto = int(arguments.get("puerto") or browser_mcp.PUERTO_POR_DEFECTO)
    except (TypeError, ValueError):
        raise CapabilityError("El puerto tiene que ser un número")
    if not 1 <= puerto <= 65535:
        raise CapabilityError(f"{puerto} no es un puerto válido")

    try:
        if accion == "arrancar":
            navegador = (
                str(arguments.get("navegador") or "").strip()
                or browser_mcp.NAVEGADOR_POR_DEFECTO
            )
            # Con qué nombre le va a llamar Morgana. Sin esto, Playwright le
            # devolvería un 403 por venir de un `Host` que no reconoce.
            hosts = str(arguments.get("hosts") or "").strip()
            # En qué interfaz escucha. Vacío = localhost, que es lo que hace
            # falta cuando el contenedor corre en esta misma máquina y además
            # deja el puerto fuera del alcance de la red.
            bind = str(arguments.get("bind") or "").strip()
            return browser_mcp.arrancar(
                puerto,
                navegador,
                host=bind or browser_mcp.HOST_POR_DEFECTO,
                hosts_permitidos=hosts,
            )
        if accion == "parar":
            return browser_mcp.parar(puerto)
        if accion == "estado":
            return browser_mcp.estado(puerto)
    except browser_mcp.BrowserMCPError as error:
        raise CapabilityError(str(error)) from error

    raise CapabilityError(
        f"No sé qué es «{accion}»: puedo arrancar, parar o mirar el estado"
    )


def _system_mcp(_: NodeConfig, arguments: dict) -> dict:
    """Enciende, apaga o consulta el servidor con el que Morgana toca este PC.

    Es el que le da el disco y el intérprete de comandos de esta máquina. Tiene
    que correr aquí por lo mismo que el navegador: Morgana vive en un contenedor
    donde este ordenador no existe.

    A diferencia del navegador, lo que devuelve incluye un secreto —el que va en
    la ruta del servidor—, así que su sitio es este canal y no un archivo.
    """
    accion = str(arguments.get("accion") or "arrancar").strip().lower()

    try:
        puerto = int(arguments.get("puerto") or system_mcp.PUERTO_POR_DEFECTO)
    except (TypeError, ValueError):
        raise CapabilityError("El puerto tiene que ser un número") from None
    if not 1 <= puerto <= 65535:
        raise CapabilityError(f"{puerto} no es un puerto válido")

    try:
        if accion == "arrancar":
            # En qué interfaz escucha. Vacío = solo localhost, que basta cuando
            # el contenedor corre en esta misma máquina y además deja el puerto
            # fuera del alcance de la red.
            bind = str(arguments.get("bind") or "").strip()
            return system_mcp.arrancar(
                puerto, bind or system_mcp.HOST_POR_DEFECTO
            )
        if accion == "parar":
            return system_mcp.parar()
        if accion == "estado":
            return system_mcp.estado()
    except system_mcp.SystemMCPError as error:
        raise CapabilityError(str(error)) from error

    raise CapabilityError(
        f"No sé qué es «{accion}»: puedo arrancar, parar o mirar el estado"
    )


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


# ---------- Transferencias ----------

def _resolver_local(config: NodeConfig, crudo: object) -> Path:
    ruta = Path(str(crudo or "").strip()).expanduser()
    if not str(ruta):
        raise CapabilityError("No has dicho qué archivo")
    if not ruta.is_absolute():
        ruta = Path(config.projects_root).expanduser() / ruta
    return ruta


def _files_stat(config: NodeConfig, arguments: dict) -> dict:
    """Cuánto pesa un archivo, para poder avisar antes de moverlo."""
    ruta = _resolver_local(config, arguments.get("ruta"))
    if not ruta.exists():
        return {"existe": False, "ruta": str(ruta)}
    info = ruta.stat()
    return {
        "existe": True,
        "ruta": str(ruta),
        "nombre": ruta.name,
        "directorio": ruta.is_dir(),
        "bytes": info.st_size if ruta.is_file() else None,
        "modificado_en": info.st_mtime,
    }


def _url_transferencia(config: NodeConfig, transfer_id: str) -> str:
    return (
        f"{config.url.rstrip('/')}/api/nodos/transferencias/"
        f"{transfer_id}/contenido"
    )


def _files_push(config: NodeConfig, arguments: dict) -> dict:
    """Sube un archivo local a Morgana para que llegue a otro dispositivo.

    Se manda el archivo abierto, no leído en memoria: httpx lo va enviando por
    trozos, así que un vídeo de varios gigas cuesta lo mismo en RAM que un .md.
    """
    transfer_id = str(arguments.get("transfer_id") or "").strip()
    if not transfer_id:
        raise CapabilityError("Falta el identificador de la transferencia")

    ruta = _resolver_local(config, arguments.get("ruta"))
    if not ruta.is_file():
        raise CapabilityError(f"No es un archivo que pueda mandar: {ruta}")

    try:
        with ruta.open("rb") as cuerpo:
            respuesta = httpx.post(
                _url_transferencia(config, transfer_id),
                content=cuerpo,
                headers={
                    "Authorization": f"Bearer {config.token}",
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(ruta.stat().st_size),
                },
                timeout=TIMEOUT_TRANSFERENCIA,
            )
    except httpx.HTTPError as error:
        raise CapabilityError(f"No pude subir el archivo: {error}") from error

    if respuesta.status_code != 200:
        raise CapabilityError(
            f"Morgana rechazó el archivo ({respuesta.status_code}): "
            f"{respuesta.text[:300]}"
        )
    return {"ruta": str(ruta), "bytes_enviados": ruta.stat().st_size}


def _nombre_seguro(crudo: object, por_defecto: str = "archivo") -> str:
    """Reduce lo que venga a un nombre de archivo suelto.

    Todo lo que huela a ruta se descarta: quien manda el archivo elige el
    nombre, nunca el sitio.
    """
    nombre = str(crudo or "").strip().replace("\x00", "")
    nombre = nombre.replace("/", " ").replace("\\", " ").strip()
    nombre = "".join(c for c in nombre if c.isprintable())
    nombre = Path(nombre).name.strip()
    if nombre in ("", ".", ".."):
        return por_defecto
    return nombre[:200]


def _nombre_libre(carpeta: Path, nombre: str) -> Path:
    destino = carpeta / nombre
    if not destino.exists():
        return destino
    tallo, sufijo = destino.stem, destino.suffix
    contador = 2
    while True:
        candidato = carpeta / f"{tallo} ({contador}){sufijo}"
        if not candidato.exists():
            return candidato
        contador += 1


def _files_pull(config: NodeConfig, arguments: dict) -> dict:
    """Baja de Morgana un archivo y lo deja en la carpeta de entrada."""
    transfer_id = str(arguments.get("transfer_id") or "").strip()
    if not transfer_id:
        raise CapabilityError("Falta el identificador de la transferencia")

    carpeta = Path(
        config.inbox_root or (Path.home() / "Morgana" / "Entrante")
    ).expanduser()
    carpeta.mkdir(parents=True, exist_ok=True)
    carpeta = carpeta.resolve()

    nombre = _nombre_seguro(arguments.get("nombre"))
    temporal = carpeta / f".{transfer_id}.parcial"
    total = 0
    try:
        with httpx.stream(
            "GET",
            _url_transferencia(config, transfer_id),
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=TIMEOUT_TRANSFERENCIA,
            follow_redirects=True,
        ) as respuesta:
            if respuesta.status_code != 200:
                respuesta.read()
                raise CapabilityError(
                    f"Morgana no me dio el archivo ({respuesta.status_code}): "
                    f"{respuesta.text[:300]}"
                )
            with temporal.open("wb") as salida:
                for trozo in respuesta.iter_bytes(1024 * 1024):
                    total += len(trozo)
                    salida.write(trozo)
    except httpx.HTTPError as error:
        temporal.unlink(missing_ok=True)
        raise CapabilityError(f"No pude bajar el archivo: {error}") from error
    except Exception:
        temporal.unlink(missing_ok=True)
        raise

    destino = _nombre_libre(carpeta, nombre)
    # Última comprobación antes de escribir: el nombre ya venía saneado, pero
    # esto es lo único que separa la carpeta de entrada del resto del disco.
    if destino.parent != carpeta:
        temporal.unlink(missing_ok=True)
        raise CapabilityError("Nombre de archivo no válido")
    os.replace(temporal, destino)
    return {"ruta": str(destino), "bytes": total}


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
    "browser.mcp": _browser_mcp,
    "system.mcp": _system_mcp,
    "open.path": _open_path,
    "files.search": _files_search,
    "files.stat": _files_stat,
    "files.push": _files_push,
    "files.pull": _files_pull,
    "media.control": _media_control,
    "media.now_playing": _media_now_playing,
}


def run(config: NodeConfig, capability: str, arguments: dict) -> dict:
    handler = HANDLERS.get(capability)
    if handler is None:
        raise CapabilityError(f"Este dispositivo no sabe hacer «{capability}»")
    return handler(config, arguments or {})

"""El disco y el intérprete de esta máquina, servidos por MCP.

Vibi vive en un contenedor y ahí dentro solo existe una carpeta del
ordenador, la del workspace. Este servidor es la otra mitad: corre aquí, con el
usuario del sistema, y le da al motor herramientas de archivos y de ejecución
que apuntan a la máquina de verdad, con sus rutas de verdad.

Es el mismo montaje que el navegador (`browser_mcp`) y por el mismo motivo: lo
que hay que tocar está aquí. La diferencia está en tres cosas:

- **Corre dentro del agente, en un hilo, y no como proceso aparte.** Ahí hacía
  falta `npx` y un programa de terceros; aquí el servidor es nuestro y en
  Python. Así el secreto vive en memoria y no hay que persistirlo.
- **No sobrevive al agente.** El navegador sí, porque cerrarlo se llevaría por
  delante una ventana que el usuario está mirando y reabrirla cuesta minutos.
  Aquí no hay nada que preservar, y un servidor huérfano sirviendo el disco con
  un token que ya nadie recuerda es justo lo que no queremos.
- **Pide credencial.** El de Playwright no la pide porque solo escucha en
  localhost; este sirve el disco entero, y el nodo puede no ser la máquina del
  contenedor. El secreto va en la ruta —`/<token>/mcp`— y no en una cabecera:
  `agy` declara los servidores remotos con `serverUrl` a secas, y una URL la
  traga cualquier cliente MCP haya o no soporte de cabeceras.
"""
from __future__ import annotations

import platform
import secrets
import socket
import threading
import time
from pathlib import Path

from . import system_fs, system_shell
from .fs_scope import FueraDeAlcance
from .system_fs import ErrorArchivo
from .system_shell import ErrorShell

PUERTO_POR_DEFECTO = 8932

# Localhost basta cuando el contenedor corre en esta misma máquina, y es lo que
# hay que preferir: `host.docker.internal` es una dirección virtual de Docker
# Desktop que el anfitrión no tiene en ningún adaptador, así que la conexión
# entra como local y el puerto no se ve desde la red. Comprobado con el
# navegador. Con el nodo en otra máquina hay que abrirlo, y entonces lo único
# que queda delante del disco es el token de la ruta.
HOST_POR_DEFECTO = "127.0.0.1"

NOMBRE_SERVIDOR = "vibi-pc"
ARRANQUE_TIMEOUT = 20.0
SONDEO = 0.1


class SystemMCPError(Exception):
    pass


_servidor = None            # uvicorn.Server
_hilo: threading.Thread | None = None
_token: str = ""
_puerto: int = 0
_bind: str = ""


def _resultado(funcion, *args, **kwargs) -> dict:
    """Llama y convierte los fallos esperables en respuesta, no en excepción.

    Un rechazo —una ruta que no existe, un fragmento que aparece dos veces— es
    información que el modelo necesita para corregir por su cuenta. Si sale
    como error del transporte, lo que ve es que la herramienta se ha roto.
    """
    try:
        return funcion(*args, **kwargs)
    except (ErrorArchivo, ErrorShell, FueraDeAlcance) as error:
        return {"error": str(error)}


def _base() -> Path:
    return Path.home()


def construir_mcp(token: str, host: str, puerto: int):
    """El servidor con sus herramientas, sin arrancarlo."""
    from mcp.server.fastmcp import FastMCP  # noqa: PLC0415 - solo si se usa
    from mcp.server.transport_security import (  # noqa: PLC0415
        TransportSecuritySettings,
    )

    mcp = FastMCP(
        NOMBRE_SERVIDOR,
        host=host,
        port=puerto,
        # El secreto va aquí dentro: quien no lo tenga se lleva un 404 sin
        # llegar a hablar MCP.
        streamable_http_path=f"/{token}/mcp",
        # Sin estado entre peticiones. Con él, un cliente que reconecte —y `agy`
        # reconecta— tendría que reanudar una sesión que el servidor ya olvidó.
        stateless_http=True,
        log_level="WARNING",
        # FastMCP protege localhost validando `Host`. Docker Desktop llega por
        # 127.0.0.1, pero conserva `host.docker.internal` en esa cabecera; si
        # no se declara, el puerto escucha y aun así todos los clientes del
        # contenedor reciben 421. Se mantiene la protección y se amplía solo
        # al alias virtual que usa Vibi, nunca a un comodín global.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "127.0.0.1:*",
                "localhost:*",
                "[::1]:*",
                "host.docker.internal:*",
            ],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
            ],
        ),
    )

    @mcp.tool()
    def info() -> dict:
        """Dónde estás: nombre del equipo, sistema y carpeta personal."""
        casa = Path.home()
        return {
            "equipo": socket.gethostname(),
            "sistema": f"{platform.system()} {platform.release()}",
            "carpeta_personal": str(casa),
            "separador": "\\" if platform.system() == "Windows" else "/",
            "escritorio": str(casa / "Desktop"),
            "descargas": str(casa / "Downloads"),
        }

    @mcp.tool()
    def listar(ruta: str) -> dict:
        """Lo que hay en una carpeta de este ordenador."""
        return _resultado(system_fs.listar, ruta, _base())

    @mcp.tool()
    def leer(ruta: str, desde: int = 1, lineas: int | None = None) -> dict:
        """Lee un archivo de texto, numerado por líneas."""
        return _resultado(system_fs.leer, ruta, desde, lineas, _base())

    @mcp.tool()
    def escribir(ruta: str, contenido: str) -> dict:
        """Crea o reemplaza un archivo entero. Crea las carpetas que falten."""
        return _resultado(system_fs.escribir, ruta, contenido, _base())

    @mcp.tool()
    def editar(ruta: str, buscar: str, reemplazar: str) -> dict:
        """Cambia un fragmento exacto por otro. Debe aparecer una sola vez."""
        return _resultado(system_fs.editar, ruta, buscar, reemplazar, _base())

    @mcp.tool()
    def buscar(patron: str = "", ruta: str = "", texto: str = "") -> dict:
        """Busca archivos por nombre (patrón glob) o por lo que contienen."""
        return _resultado(system_fs.buscar, patron, ruta or None, texto, _base())

    @mcp.tool()
    def ejecutar(comando: str, directorio: str = "", timeout: int = 120) -> dict:
        """Ejecuta un comando y espera. PowerShell en Windows, la shell en Mac."""
        return _resultado(
            system_shell.ejecutar, comando, directorio or None, timeout, _base()
        )

    @mcp.tool()
    def lanzar(comando: str, directorio: str = "") -> dict:
        """Arranca algo largo y vuelve enseguida con su identificador."""
        return _resultado(system_shell.lanzar, comando, directorio or None, _base())

    @mcp.tool()
    def progreso(trabajo: str, desde: int = 0) -> dict:
        """Por dónde va un trabajo lanzado y qué ha escrito desde `desde`."""
        return _resultado(system_shell.salida, trabajo, desde)

    @mcp.tool()
    def parar_trabajo(trabajo: str) -> dict:
        """Corta un trabajo que sigue corriendo."""
        return _resultado(system_shell.parar, trabajo)

    @mcp.tool()
    def trabajos() -> dict:
        """Los trabajos lanzados y en qué estado están."""
        return _resultado(system_shell.trabajos)

    return mcp


def escuchando(puerto: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    destino = "127.0.0.1" if host in ("", "0.0.0.0") else host
    try:
        with socket.create_connection((destino, puerto), timeout=timeout):
            return True
    except OSError:
        return False


def _arrancar_hilo(mcp, host: str, puerto: int) -> None:
    global _servidor, _hilo

    import uvicorn  # noqa: PLC0415 - solo hace falta al levantar el servidor

    class _Servidor(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            # uvicorn registra manejadores de señal al servir, y eso solo se
            # puede hacer desde el hilo principal: sin esto, arrancar en un hilo
            # revienta con «set_wakeup_fd only works in main thread».
            return

    aplicacion = mcp.streamable_http_app()
    configuracion = uvicorn.Config(
        aplicacion, host=host, port=puerto, log_level="warning", access_log=False
    )
    _servidor = _Servidor(configuracion)
    _hilo = threading.Thread(
        target=_servidor.run, name="vibi-system-mcp", daemon=True
    )
    _hilo.start()


def buscar_puerto_libre(
    puerto_base: int = PUERTO_POR_DEFECTO,
    host: str = HOST_POR_DEFECTO,
    max_intentos: int = 100,
) -> int:
    """Busca el primer puerto libre a partir de puerto_base o asigna uno del sistema."""
    host_bind = "0.0.0.0" if host in ("", "0.0.0.0") else host
    if puerto_base <= 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host_bind, 0))
            return s.getsockname()[1]

    for p in range(puerto_base, puerto_base + max_intentos):
        if not escuchando(p, host):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((host_bind, p))
                    return p
            except OSError:
                continue

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host_bind, 0))
            return s.getsockname()[1]
    except OSError:
        return puerto_base


def arrancar(
    puerto: int = PUERTO_POR_DEFECTO, bind: str = HOST_POR_DEFECTO
) -> dict:
    """Deja el servidor en pie y devuelve dónde escucha y con qué secreto.

    Es idempotente mientras no cambien puerto ni interfaz: Vibi lo llama al
    abrir cada sesión del motor, y levantar otro serviría para nada. Si cambian,
    se para el que hay y se abre uno nuevo, porque el anterior estaría
    escuchando donde ya no se le llama. Si el puerto preferido está ocupado,
    busca automáticamente el siguiente puerto libre.
    """
    global _token, _puerto, _bind

    host = (bind or HOST_POR_DEFECTO).strip() or HOST_POR_DEFECTO

    if _vivo():
        if (_puerto, _bind) == (puerto, host) or (
            puerto in (0, PUERTO_POR_DEFECTO) and _bind == host and _puerto > 0
        ):
            return _describir(arrancado_ahora=False)
        parar()

    puerto_efectivo = puerto
    if puerto_efectivo <= 0 or escuchando(puerto_efectivo, host):
        puerto_efectivo = buscar_puerto_libre(
            puerto_base=puerto if puerto > 0 else PUERTO_POR_DEFECTO,
            host=host,
        )

    # Un secreto nuevo en cada arranque. No se guarda en ningún sitio: viaja al
    # servidor por el WebSocket del nodo, que ya está autenticado, y ahí acaba
    # su recorrido. Reiniciar el agente lo invalida, que es lo que queremos.
    token = secrets.token_urlsafe(24)
    try:
        mcp = construir_mcp(token, host, puerto_efectivo)
    except ImportError as error:
        raise SystemMCPError(
            f"Falta una dependencia del servidor MCP ({error}). Instala los "
            f"requisitos del agente: pip install -r agent/requirements.txt"
        ) from error

    _arrancar_hilo(mcp, host, puerto_efectivo)

    limite = time.time() + ARRANQUE_TIMEOUT
    while time.time() < limite:
        if escuchando(puerto_efectivo, host):
            _token, _puerto, _bind = token, puerto_efectivo, host
            return _describir(arrancado_ahora=True)
        if _hilo is not None and not _hilo.is_alive():
            raise SystemMCPError("El servidor MCP del sistema se cerró al arrancar")
        time.sleep(SONDEO)

    parar()
    raise SystemMCPError(
        f"El servidor MCP del sistema no abrió el puerto {puerto_efectivo} en "
        f"{ARRANQUE_TIMEOUT:.0f}s"
    )


def _vivo() -> bool:
    return _hilo is not None and _hilo.is_alive()


def _describir(arrancado_ahora: bool) -> dict:
    return {
        "estado": "ok",
        "puerto": _puerto,
        "bind": _bind,
        # El servidor de Vibi compone la URL con el nombre por el que él ve
        # esta máquina, que no tiene por qué ser el que veamos nosotros.
        "ruta": f"/{_token}/mcp",
        "token": _token,
        "arrancado_ahora": arrancado_ahora,
    }


def parar() -> dict:
    global _servidor, _hilo, _token, _puerto, _bind

    if not _vivo():
        _servidor = _hilo = None
        _token, _puerto, _bind = "", 0, ""
        return {"estado": "ok", "parado": False}

    if _servidor is not None:
        _servidor.should_exit = True
    if _hilo is not None:
        _hilo.join(timeout=10)

    parado = not _vivo()
    _servidor = _hilo = None
    _token, _puerto, _bind = "", 0, ""
    return {"estado": "ok", "parado": parado}


def estado() -> dict:
    if not _vivo():
        return {"estado": "ok", "escuchando": False}
    return {
        "estado": "ok",
        "escuchando": escuchando(_puerto, _bind),
        "puerto": _puerto,
        "bind": _bind,
        "ruta": f"/{_token}/mcp",
        "token": _token,
    }

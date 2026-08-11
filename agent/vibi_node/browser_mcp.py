"""El servidor MCP de Playwright, corriendo aquí para que veas el navegador.

`agy` vive dentro del contenedor y cualquier navegador que abriera ahí sería
invisible: sin servidor gráfico, en otra máquina a efectos prácticos. Por eso
Playwright no corre allí sino aquí, en el escritorio del usuario, y `agy` se
conecta a él por red (`serverUrl` en su configuración MCP).

Este módulo no habla MCP ni Playwright: solo se encarga de que el proceso
`npx @playwright/mcp` esté en pie y escuchando. Quien pilota el navegador es
`agy`; nosotros ponemos la ventana delante de los ojos del usuario.

El proceso sobrevive al agente a propósito. Matarlo al cerrar el companion se
llevaría por delante la ventana que el usuario está mirando, y reabrirla
cuesta la descarga de `npx` otra vez; en vez de eso, al arrancar se comprueba
si el puerto ya contesta y se reaprovecha lo que hubiera.
"""
from __future__ import annotations

import http.client
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from .config import compatible_path, environment_value

PAQUETE = "@playwright/mcp@latest"
# El paquete sin versión, que es lo que se busca en la orden de un proceso para
# reconocerlo como nuestro. Va aparte para que cambiar la versión de arriba no
# deje huérfano un servidor lanzado por la anterior.
NOMBRE_PAQUETE = "@playwright/mcp"
PUERTO_POR_DEFECTO = 8931
# Para decirle dónde está `npx` cuando no se puede deducir. Ver `_npx`.
VARIABLE_NPX = "VIBI_NPX"
LEGACY_VARIABLE_NPX = "MORGANA_NPX"
NAVEGADOR_POR_DEFECTO = "chrome"

# Los dos modos de tener navegador, que se diferencian en quién es su dueño.
#
# `cdp`: Playwright se engancha al navegador del usuario, que ya estaba abierto
# con su perfil y sus sesiones. Abre pestañas al lado de las suyas y no cierra
# nada al terminar, porque el navegador no es suyo. Es lo que se quiere.
#
# `perfil`: Playwright lanza y posee un navegador con un perfil aparte, sin
# ninguna sesión iniciada. Era lo único que había antes y se mantiene entero
# como repliegue: si un día el puerto de depuración deja de estar disponible,
# se cambia una variable y se sigue navegando.
MODO_CDP = "cdp"
MODO_PERFIL = "perfil"

# Localhost basta, y no es evidente: parecería que el contenedor necesita que
# el puerto escuche en todas las interfaces. No lo necesita. Docker Desktop
# hace de intermediario —`host.docker.internal` es una dirección suya, virtual,
# que el anfitrión no tiene en ningún adaptador—, así que la conexión llega
# como si viniera de esta misma máquina. Medido: con este valor el contenedor
# recibe su 200 y el puerto no se ve ni desde la red local ni desde la tailnet.
#
# Importa porque el servidor no pide credenciales: quien lo alcance pilota el
# navegador con las sesiones que tengas abiertas en su perfil. Abrirlo a la red
# y taparlo con el cortafuegos era peor que no abrirlo.
#
# Con el nodo en otra máquina distinta de la del contenedor esto no vale, y hay
# que pasar un `host` explícito sabiendo lo que se expone.
HOST_POR_DEFECTO = "127.0.0.1"

# La primera vez `npx` se descarga el paquete entero antes de abrir el puerto,
# y eso con una conexión mala pasa del minuto. Las siguientes tarda un par de
# segundos.
ARRANQUE_TIMEOUT = 120.0
SONDEO = 0.25

# Un perfil propio, aparte del Chrome de diario. No es manía de aislamiento:
# Chrome no deja dos instancias sobre el mismo directorio de perfil, así que
# compartirlo significaría no poder navegar mientras Vibi navega.
PERFIL = "vibi-playwright"
LEGACY_PERFIL = "morgana-playwright"


class BrowserMCPError(Exception):
    pass


# El proceso lanzado desde este agente, si fue este quien lo lanzó. Puede estar
# a None y el servidor seguir en pie: lo dice el puerto, no esta variable.
_proceso: subprocess.Popen | None = None

# A qué navegador está enganchado el servidor que hay en pie, si lo está. Hace
# falta porque el puerto contestando ya no significa «esto sirve»: un servidor
# que lanzamos en modo perfil sigue escuchando igual, y reaprovecharlo dejaría a
# Vibi navegando en el Chrome vacío justo después de pedir lo contrario.
_endpoint: str = ""


def _marca(perfil: Path) -> Path:
    return perfil / "servidor.json"


def _leer_marca(perfil: Path) -> dict:
    """A qué navegador quedó enganchado el último servidor que lanzamos.

    La misma pregunta que responde `_endpoint`, pero para cuando el agente se
    ha reiniciado y esa variable ha vuelto a nacer vacía. Sin esto el cambio de
    modo falla de la peor manera: el servidor viejo sigue escuchando el puerto,
    se da por bueno porque contesta, y Vibi navega en el navegador de antes
    sin que nada lo denuncie. El síntoma es «lo he cambiado y no hace nada».
    """
    try:
        marca = json.loads(_marca(perfil).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return marca if isinstance(marca, dict) else {}


def _escribir_marca(perfil: Path, endpoint: str, pid: int) -> None:
    """Deja apuntado lo que hará falta saber en el próximo arranque."""
    try:
        _marca(perfil).write_text(
            json.dumps({"endpoint": endpoint, "pid": pid}), encoding="utf-8"
        )
    except OSError:
        pass  # saberlo es deseable, no imprescindible


def _orden(pid: int) -> str:
    """Con qué se lanzó ese proceso, o cadena vacía si ya no está.

    Se mira la orden entera y no el nombre de la imagen porque el nombre no
    distingue: en Windows el proceso que arranca de todo esto es un `cmd.exe`
    —lo que abre `Popen` al lanzar un `.cmd`—, y hay cientos.
    """
    try:
        if sys.platform == "win32":
            return subprocess.run(  # noqa: S603 - argv es nuestro
                [
                    "powershell", "-NoProfile", "-NonInteractive", "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')"
                    ".CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
        return Path(f"/proc/{pid}/cmdline").read_text(encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        return ""


def _es_nuestro_servidor(pid: int) -> bool:
    """¿Ese pid sigue siendo el servidor MCP, y no un número reciclado?

    Se comprueba antes de matar nada. El sistema reutiliza los pid y la marca
    puede llevar días en disco: sin esto, un número que ahora es de otra cosa
    se convierte en un proceso ajeno muerto por sorpresa.
    """
    return NOMBRE_PAQUETE in _orden(pid)


def _matar_arbol(pid: int) -> None:
    """Se lleva por delante también a los hijos, que es donde está el servidor.

    Costó descubrirlo y explica por qué cambiar de modo no servía de nada: lo
    que devuelve `Popen` en Windows es el `cmd.exe` que envuelve a `npx.cmd`, y
    quien escucha el puerto es un `node` **cuatro niveles por debajo**
    (cmd → node → cmd → node). Cerrar solo el primero deja el puerto ocupado
    por un servidor huérfano, y el que se lanza después se muere al no poder
    quedarse con el puerto.

    Aquí sí se fuerza, al revés que con el navegador: esto es un proceso
    nuestro sin nada que guardar, y en modo `cdp` ni siquiera se lleva ninguna
    ventana por delante, porque el navegador no es suyo.
    """
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603 - argv es nuestro
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        os.kill(pid, signal.SIGTERM)


def _matar_pid(pid: int) -> bool:
    """Cierra el servidor que dejó una ejecución anterior de este agente."""
    if not _es_nuestro_servidor(pid):
        return False
    try:
        _matar_arbol(pid)
    except (OSError, subprocess.SubprocessError):
        return False
    for _ in range(40):  # hasta 10 s
        if not _es_nuestro_servidor(pid):
            return True
        time.sleep(SONDEO)
    return False


def _perfil_por_defecto() -> Path:
    """Dónde guardar el perfil del navegador, según el sistema."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        root = Path(base)
    else:
        root = Path.home() / ".cache"
    return compatible_path(root / PERFIL, root / LEGACY_PERFIL)


def escuchando(puerto: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """¿Hay alguien atendiendo ese puerto?

    Se pregunta por TCP y no por HTTP a propósito: el servidor abre el puerto
    antes de tener rutas listas, y lo que nos interesa saber es si hace falta
    lanzar otro proceso, no si ya responde a una petición concreta.
    """
    try:
        with socket.create_connection((host, puerto), timeout=timeout):
            return True
    except OSError:
        return False


def hosts_con_puerto(hosts: str, puerto: int) -> str:
    """Cada nombre, con puerto y sin él.

    Playwright compara el `Host` recibido tal cual, y un cliente HTTP normal lo
    manda con el puerto pegado (`host.docker.internal:8931`) siempre que no sea
    el de su esquema. Declarar solo el nombre pelado deja fuera justo la forma
    que va a llegar, y el resultado es un 403 en cada petición.
    """
    formas: list[str] = []
    for crudo in hosts.split(","):
        nombre = crudo.strip()
        if not nombre:
            continue
        base = nombre.rsplit(":", 1)[0] if ":" in nombre else nombre
        for forma in (base, f"{base}:{puerto}"):
            if forma not in formas:
                formas.append(forma)
    return ",".join(formas)


def acepta_host(puerto: int, host: str, timeout: float = 2.0) -> bool:
    """¿Atendería a quien le llame por ese nombre?

    Escuchar no basta. Playwright rechaza con 403 las peticiones que le llegan
    con un `Host` que no reconoce, así que un servidor levantado antes —sin el
    permiso, o con otro nombre— seguiría ahí ocupando el puerto y `agy` se
    comería un 403 en cada intento. Se pregunta poniendo el mismo `Host` que va
    a poner él, con el puerto incluido, que es como lo manda un cliente normal.
    """
    conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=timeout)
    try:
        nombre = host.rsplit(":", 1)[0] if ":" in host else host
        conexion.request("GET", "/", headers={"Host": f"{nombre}:{puerto}"})
        # Cualquier cosa que no sea 403 vale: un 400 o un 404 significan que la
        # petición llegó a pasar el filtro, que es lo único que se pregunta.
        return conexion.getresponse().status != 403
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conexion.close()


def _npx() -> str:
    """Localiza `npx`, que no siempre está donde debería.

    En Windows el ejecutable es `npx.cmd`, y `which` lo resuelve mirando
    PATHEXT —cosa que `Popen` sin shell no hace por su cuenta—. Cuando no está
    en el PATH se busca junto a `node`, que es donde lo dejan los instaladores
    aunque la carpeta no esté publicada.

    `VIBI_NPX` gana a todo. Hace falta con gestores de versiones como nvm,
    donde la versión activa puede no traer npm y la que sí lo trae está en un
    directorio que nadie ha publicado en el PATH.
    """
    declarado = environment_value(VARIABLE_NPX, LEGACY_VARIABLE_NPX).strip()
    if declarado:
        if not Path(declarado).exists():
            raise BrowserMCPError(
                f"{VARIABLE_NPX} apunta a {declarado}, que no existe"
            )
        return declarado

    ruta = shutil.which("npx")
    if ruta is not None:
        return ruta

    node = shutil.which("node")
    if node is not None:
        vecino = shutil.which("npx", path=str(Path(node).parent))
        if vecino is not None:
            return vecino

    raise BrowserMCPError(
        "No encuentro npx. Hace falta Node.js *con npm* para abrir el "
        "navegador desde Vibi: comprueba `npx --version` en una consola. Si "
        f"usas nvm y la versión activa no trae npm, apunta {VARIABLE_NPX} al "
        "npx.cmd de una que sí lo tenga."
    )


def comando(
    puerto: int,
    navegador: str,
    perfil: Path,
    host: str,
    hosts_permitidos: str = "",
    cdp_endpoint: str = "",
) -> list[str]:
    """La línea de comandos del servidor, separada para poder comprobarla."""
    argv = [
        _npx(),
        "--yes",
        PAQUETE,
        "--port", str(puerto),
        "--host", host,
        # Sin esto, los volcados de página y las capturas caen en el directorio
        # desde el que se lanzó el servidor —el del agente, o peor, el repo en
        # el que estuvieras—. Van con el perfil, que es donde se esperan.
        "--output-dir", str(perfil / "salidas"),
    ]
    if cdp_endpoint:
        # Enganchado al navegador del usuario. `--browser` y `--user-data-dir`
        # no van, y no es que sobren: describen un navegador que habría que
        # lanzar, y aquí no se lanza ninguno.
        argv += ["--cdp-endpoint", cdp_endpoint]
    else:
        argv += ["--browser", navegador, "--user-data-dir", str(perfil)]
    if hosts_permitidos:
        # Playwright comprueba con qué nombre le han llamado y rechaza con 403
        # el que no reconozca: es su defensa contra que una web cualquiera que
        # estés visitando se ponga a mandarle órdenes por DNS rebinding. Como
        # `agy` le llama por `host.docker.internal` y no por `localhost`, hay
        # que declararlo. Se pasan los nombres exactos y no `*` para que la
        # defensa siga en pie frente a todos los demás.
        argv += ["--allowed-hosts", hosts_con_puerto(hosts_permitidos, puerto)]
    return argv


def ruta_log(perfil: Path) -> Path:
    return perfil / "servidor.log"


def _lanzar(argv: list[str], perfil: Path) -> subprocess.Popen:
    """Arranca el servidor sin que le salga una consola por delante.

    Va desligado de este proceso para que cerrar el agente no cierre el
    navegador que el usuario tiene abierto.

    La salida va a un archivo y no al vertedero. Tirarla salía barato hasta que
    hubo que averiguar por qué un cliente no se conectaba: sin este log no hay
    forma de saber si alguien llegó a llamar a la puerta. Se reescribe en cada
    arranque para que no crezca sin fin. Lo que no vale es dejar las tuberías
    sin vaciar: el servidor se bloquearía al llenarse el buffer.
    """
    try:
        salida = open(ruta_log(perfil), "w", encoding="utf-8", errors="replace")
    except OSError:
        salida = subprocess.DEVNULL  # un log es deseable, no imprescindible

    opciones: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": salida,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        opciones["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        opciones["start_new_session"] = True
    try:
        return subprocess.Popen(argv, **opciones)  # noqa: S603 - argv es nuestro
    except OSError as error:
        raise BrowserMCPError(f"No se pudo lanzar el servidor MCP: {error}") from error


def arrancar(
    puerto: int = PUERTO_POR_DEFECTO,
    navegador: str = NAVEGADOR_POR_DEFECTO,
    host: str = HOST_POR_DEFECTO,
    perfil: Path | None = None,
    timeout: float = ARRANQUE_TIMEOUT,
    hosts_permitidos: str = "",
    cdp_endpoint: str = "",
) -> dict:
    """Deja el servidor en pie y devuelve dónde escucha.

    Es idempotente: si el puerto ya contesta no lanza nada. Eso cubre tanto la
    llamada repetida —Vibi la hace al abrir cada sesión de `agy`— como el
    servidor que sobrevivió a un reinicio del agente.

    `cdp_endpoint` engancha el servidor al navegador del usuario en vez de
    lanzarle uno propio. Vacío es el modo perfil de siempre.
    """
    global _proceso, _endpoint

    nuestro = _proceso is not None and _proceso.poll() is None
    destino = Path(perfil) if perfil else _perfil_por_defecto()

    if escuchando(puerto):
        # Un servidor heredado —del que solo queda la marca en disco— cuenta
        # como nuestro para esto: lo lanzó este agente en otra ejecución, y
        # saber a qué navegador quedó enganchado es justo lo que evita
        # reaprovecharlo cuando se acaba de cambiar de modo.
        marca = {} if nuestro else _leer_marca(destino)
        anterior = _endpoint if nuestro else marca.get("endpoint", "")
        conocido = nuestro or bool(marca)
        sirve = anterior == cdp_endpoint if conocido else True
        if sirve and (
            not hosts_permitidos or acepta_host(puerto, hosts_permitidos.split(",")[0])
        ):
            return {
                "estado": "ok",
                "puerto": puerto,
                "arrancado_ahora": False,
                "pid": _proceso.pid if nuestro else marca.get("pid"),
                "cdp_endpoint": anterior,
            }
        if nuestro:
            # Nuestro pero apuntando a otro sitio: se ha cambiado de modo entre
            # una sesión y la siguiente.
            _terminar(_proceso)
        elif not (marca.get("pid") and _matar_pid(int(marca["pid"]))):
            # Ocupado por algo que no hemos lanzado, o que no hemos podido
            # cerrar. Matar a ciegas lo que escuche un puerto sería peor que
            # decirlo.
            raise BrowserMCPError(
                f"El puerto {puerto} ya está ocupado por un servidor que no "
                f"sirve para esto y que no he podido cerrar. Ciérralo a mano o "
                f"elige otro puerto."
            )
    elif nuestro:
        # Vivo pero sin puerto: se quedó a medias o está descargando todavía.
        # Matarlo y empezar de cero es más rápido que adivinar en qué punto va.
        _terminar(_proceso)
    _proceso = None
    _endpoint = ""

    destino.mkdir(parents=True, exist_ok=True)
    proceso = _lanzar(
        comando(puerto, navegador, destino, host, hosts_permitidos, cdp_endpoint),
        destino,
    )

    limite = time.time() + timeout
    while time.time() < limite:
        if escuchando(puerto):
            _proceso = proceso
            _endpoint = cdp_endpoint
            _escribir_marca(destino, cdp_endpoint, proceso.pid)
            return {
                "estado": "ok",
                "puerto": puerto,
                "arrancado_ahora": True,
                "pid": proceso.pid,
                "perfil": str(destino),
                "cdp_endpoint": cdp_endpoint,
            }
        if proceso.poll() is not None:
            culpa = (
                f"que el navegador siga escuchando en {cdp_endpoint}"
                if cdp_endpoint
                else f"que el navegador «{navegador}» está instalado"
            )
            raise BrowserMCPError(
                f"El servidor MCP de Playwright se cerró solo (código "
                f"{proceso.returncode}). Comprueba que Node.js funciona y "
                f"{culpa}."
            )
        time.sleep(SONDEO)

    _terminar(proceso)
    raise BrowserMCPError(
        f"El servidor MCP de Playwright no abrió el puerto {puerto} en "
        f"{timeout:.0f}s"
    )


def parar(puerto: int = PUERTO_POR_DEFECTO, perfil: Path | None = None) -> dict:
    """Cierra el servidor MCP.

    En modo perfil se lleva por delante la ventana del navegador, que era suya.
    En modo `cdp` no: el navegador es del usuario y sigue donde estaba, con sus
    pestañas. Es la diferencia práctica más visible entre los dos modos.

    Solo puede cerrar el servidor que lanzó este agente. Uno heredado de una
    ejecución anterior sigue siendo suyo, y matarlo a ciegas por el puerto
    podría llevarse por delante otra cosa que estuviera escuchando ahí.
    """
    global _proceso, _endpoint

    # La marca se borra en los dos caminos: apunta a un servidor que ya no
    # está, y dejarla haría que el arranque siguiente intentara cerrar un pid
    # muerto en vez de reaprovechar lo que hubiera.
    try:
        _marca(Path(perfil) if perfil else _perfil_por_defecto()).unlink()
    except OSError:
        pass

    if _proceso is None or _proceso.poll() is not None:
        _proceso = None
        _endpoint = ""
        return {"estado": "ok", "parado": False, "escuchando": escuchando(puerto)}

    _terminar(_proceso)
    _proceso = None
    _endpoint = ""
    return {"estado": "ok", "parado": True, "escuchando": escuchando(puerto)}


def estado(puerto: int = PUERTO_POR_DEFECTO) -> dict:
    return {
        "estado": "ok",
        "puerto": puerto,
        "escuchando": escuchando(puerto),
        "nuestro": _proceso is not None and _proceso.poll() is None,
    }


def _terminar(proceso: subprocess.Popen) -> None:
    """Cierra el servidor entero, y no solo el proceso que lo lanzó.

    `terminate()` a secas no vale: mata al envoltorio y deja escuchando al hijo
    que hace el trabajo. Ver `_matar_arbol`.
    """
    try:
        _matar_arbol(proceso.pid)
        proceso.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proceso.kill()
    except (OSError, subprocess.SubprocessError):
        pass  # ya no estaba

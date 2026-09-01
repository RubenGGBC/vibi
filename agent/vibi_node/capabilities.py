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

from . import (
    app_catalog,
    browser_enganche,
    browser_mcp,
    computer,
    inventario,
    media,
    navegador_real,
    proceso,
    screen,
    system_mcp,
    system_shell,
)
from .config import NodeConfig

MAX_PROJECTS = 200
MAX_RESULTADOS_BUSQUEDA = 100

# Cuánto se bloquea una orden esperando el resultado. Después el comando sigue
# bajo `system_shell` y la orden vuelve con un identificador. El máximo queda
# por debajo de los 45 s que el servidor espera una respuesta del nodo.
SHELL_TIMEOUT_DEFAULT = 30
SHELL_TIMEOUT_MAX = 40

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

    try:
        return system_shell.ejecutar(comando, directorio, timeout)
    except system_shell.ErrorShell as error:
        raise CapabilityError(str(error)) from error


def _shell_status(_: NodeConfig, arguments: dict) -> dict:
    trabajo = str(arguments.get("trabajo") or "").strip()
    try:
        return system_shell.salida(trabajo, int(arguments.get("desde") or 0))
    except (TypeError, ValueError, system_shell.ErrorShell) as error:
        raise CapabilityError(str(error)) from error


def _shell_stop(_: NodeConfig, arguments: dict) -> dict:
    trabajo = str(arguments.get("trabajo") or "").strip()
    try:
        return system_shell.parar(trabajo)
    except system_shell.ErrorShell as error:
        raise CapabilityError(str(error)) from error


# ---------- Escritorio ----------

def _abrir_en_escritorio(objetivo: str) -> None:
    """Entrega algo al escritorio para que lo abra con su aplicación normal.

    Cada sistema tiene su propio verbo. En Windows `start` es una palabra del
    intérprete, no un programa, así que hay que invocarlo a través de él.
    """
    sistema = platform.system()
    if sistema == "Darwin":
        subprocess.Popen(["open", objetivo], stdin=subprocess.DEVNULL, **proceso.sin_ventana())
    elif sistema == "Windows":
        os.startfile(objetivo)  # noqa: S606 - es la vía nativa en Windows
    else:
        lanzador = shutil.which("xdg-open")
        if lanzador is None:
            raise CapabilityError(
                "No encuentro xdg-open: este escritorio no sabe abrir enlaces"
            )
        subprocess.Popen([lanzador, objetivo], stdin=subprocess.DEVNULL, **proceso.sin_ventana())


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


def _cdp_puerto(arguments: dict) -> int:
    """El puerto de depuración del navegador, validado."""
    try:
        puerto = int(arguments.get("cdp_puerto") or navegador_real.PUERTO_POR_DEFECTO)
    except (TypeError, ValueError):
        raise CapabilityError(
            "El puerto de depuración tiene que ser un número"
        ) from None
    if not 1 <= puerto <= 65535:
        raise CapabilityError(f"{puerto} no es un puerto válido")
    return puerto


def _navegador_del_usuario(arguments: dict) -> tuple[str, dict]:
    """Deja el navegador del usuario listo y dice a qué endpoint engancharse.

    Devuelve endpoint vacío en modo perfil, que es como decirle a `browser_mcp`
    que se lance su propio navegador, como hacía antes.

    Un fallo aquí no es cosa del servidor MCP sino del navegador —cerrado a
    medias, ruta mal declarada—, y por eso el mensaje viaja tal cual: se lo va a
    encontrar el usuario, y «no existe el navegador: D:\\Opera\\opera.exe» se
    arregla solo leyéndolo.
    """
    modo = str(arguments.get("modo") or browser_mcp.MODO_PERFIL).strip().lower()
    if modo != browser_mcp.MODO_CDP:
        return "", {}

    try:
        listo = navegador_real.asegurar(
            _cdp_puerto(arguments),
            str(arguments.get("navegador_ruta") or "").strip(),
        )
    except navegador_real.NavegadorError as error:
        raise CapabilityError(str(error)) from error

    return listo["endpoint"], listo


# Lo que puede durar dejar la conexión hecha, contando los dos intentos y el
# pre-vuelo. El techo real no lo pone esto sino el servidor, que da una orden de
# nodo por perdida a los 45 s (`node_result_timeout_seconds`) y le dice al
# usuario que su PC no ha contestado. Dentro de esos 45 s va también abrir el
# navegador si hiciera falta, así que aquí no cabe más que esto.
PRESUPUESTO_ENGANCHE = 22.0


def _asegurar_enganche(
    puerto: int,
    hosts: str,
    cdp_puerto: int,
    presupuesto: float = PRESUPUESTO_ENGANCHE,
) -> dict:
    """Deja la conexión al navegador ya hecha, y no pendiente de hacerse.

    Es el arreglo del fallo más caro que tenía el navegador de Vibi. El
    servidor MCP en pie no significa que Playwright esté conectado: se engancha
    en la primera llamada a una herramienta, que puede ser una hora después de
    abrirse la sesión. Para entonces Opera ya ha descartado las pestañas que no
    estabas mirando, y `connectOverCDP` —que espera a que se inicialicen todas—
    se cuelga hasta rendirse. Como el fallo no se guarda, la llamada siguiente
    vuelve a pagarlo entero, y así todas.

    Se llama primero y se despierta después, y no al revés, porque despertar
    una pestaña es recargarla: si el navegador ya contesta no hay por qué
    tocarle nada al usuario, y eso es además lo normal. El fallo del primer
    intento es justamente la señal de que hay alguna descartada.

    Todo va contra reloj, y esa es la parte que costó una avería: sin el
    presupuesto, el camino de recuperación —rendirse, sondear doce pestañas,
    recargar las mudas, reintentar— pasaba de los 45 s que el servidor espera
    por una orden, y el usuario se quedaba sin navegador **por culpa de lo que
    iba a arreglárselo**. Cuando no queda tiempo se devuelve el fallo tal cual:
    el servidor MCP está en pie igual, y el modelo lo reintentará por su cuenta
    con las pestañas ya despiertas.
    """
    limite = time.monotonic() + presupuesto
    enganche = browser_enganche.enganchar(
        puerto, hosts, min(browser_enganche.TIMEOUT, presupuesto)
    )
    if enganche.get("enganchado"):
        return enganche

    restante = limite - time.monotonic()
    if restante <= 1.0:
        # Ni para despertar ni para reintentar. Recargarle las pestañas sin
        # poder aprovecharlo después es cobrarle al usuario y no darle nada.
        enganche["sin_tiempo"] = True
        return enganche

    # Al pre-vuelo se le deja como mucho la mitad de lo que quede: la otra mitad
    # es para el reintento, y despertar sin reintentar no sirve de nada.
    pestanas = navegador_real.despertar_pestanas(cdp_puerto, restante / 2)
    segundo = dict(
        browser_enganche.enganchar(
            puerto,
            hosts,
            max(1.0, min(browser_enganche.TIMEOUT, limite - time.monotonic())),
        )
    )
    segundo["pestanas"] = pestanas
    segundo["primer_error"] = enganche.get("error", "")
    return segundo


def _browser_mcp(_: NodeConfig, arguments: dict) -> dict:
    """Enciende, apaga o consulta el servidor con el que Vibi navega aquí.

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
            # Con qué nombre le va a llamar Vibi. Sin esto, Playwright le
            # devolvería un 403 por venir de un `Host` que no reconoce.
            hosts = str(arguments.get("hosts") or "").strip()
            # En qué interfaz escucha. Vacío = localhost, que es lo que hace
            # falta cuando el contenedor corre en esta misma máquina y además
            # deja el puerto fuera del alcance de la red.
            bind = str(arguments.get("bind") or "").strip()
            endpoint, navegador_listo = _navegador_del_usuario(arguments)
            salida = browser_mcp.arrancar(
                puerto,
                navegador,
                host=bind or browser_mcp.HOST_POR_DEFECTO,
                hosts_permitidos=hosts,
                cdp_endpoint=endpoint,
            )
            if navegador_listo:
                salida["navegador_real"] = navegador_listo
            if endpoint:
                # Con el puerto que haya quedado, que no siempre es el pedido:
                # si el preferido estaba ocupado, `arrancar` busca otro, y es
                # ese el que lleva declarado el nombre por el que se le llama.
                salida["enganche"] = _asegurar_enganche(
                    int(salida.get("puerto") or puerto), hosts, _cdp_puerto(arguments)
                )
            return salida
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
    """Enciende, apaga o consulta el servidor con el que Vibi toca este PC.

    Es el que le da el disco y el intérprete de comandos de esta máquina. Tiene
    que correr aquí por lo mismo que el navegador: Vibi vive en un contenedor
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

    # El índice del sistema primero y el recorrido como repliegue. Lo que había
    # aquí era un `rglob` desde la raíz, y en el histórico de esta máquina daba
    # una mediana de 300 s con cuatro búsquedas caducadas de catorce. Ver
    # `buscador` para las medidas y el porqué de cada mitad.
    from . import buscador

    return buscador.buscar(patron, raiz, MAX_RESULTADOS_BUSQUEDA)


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
    """Sube un archivo local a Vibi para que llegue a otro dispositivo.

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
            f"Vibi rechazó el archivo ({respuesta.status_code}): "
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
    """Baja de Vibi un archivo y lo deja en la carpeta de entrada."""
    transfer_id = str(arguments.get("transfer_id") or "").strip()
    if not transfer_id:
        raise CapabilityError("Falta el identificador de la transferencia")

    carpeta = Path(
        config.inbox_root or (Path.home() / "Vibi" / "Entrante")
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
                    f"Vibi no me dio el archivo ({respuesta.status_code}): "
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


# ---------- Pantalla ----------

def _capturar_una_ventana(arguments: dict) -> dict:
    """Fotografía una ventana concreta, esté donde esté.

    Es la única captura que sirve en la trastienda: ahí no hay pantalla que
    fotografiar, así que se le pide a la ventana que se dibuje. Fuera de la
    trastienda también vale, y de hecho es mejor para mirar una aplicación
    tapada: sale ella sola, sin lo que tenga encima.
    """
    import os
    import tempfile
    from pathlib import Path

    from . import ui_windows

    titulo = str(arguments.get("ventana") or "").strip()

    def trabajo():
        if titulo:
            objetivo, _ = ui_windows.elegir_ventana(titulo)
        else:
            abiertas = [v for v in ui_windows.ventanas() if not v.minimizada]
            if not abiertas:
                raise screen.ErrorPantalla(
                    "No hay ninguna ventana abierta ahí que fotografiar."
                )
            # Sin decir cuál, la de delante; y si no se sabe, la más grande.
            delante = ui_windows.handle_en_primer_plano()
            objetivo = next(
                (v for v in abiertas if v.handle == delante),
                max(
                    abiertas,
                    key=lambda v: (v.rect.derecha - v.rect.izquierda)
                    * (v.rect.abajo - v.rect.arriba),
                ),
            )

        descriptor, ruta = tempfile.mkstemp(prefix="vibi-ventana-", suffix=".jpg")
        os.close(descriptor)
        destino = Path(ruta)
        try:
            return screen.capturar_ventana(objetivo.handle, destino),                 destino.read_bytes(), objetivo.titulo
        finally:
            destino.unlink(missing_ok=True)

    detalle, imagen, titulo_real = _alli(arguments, trabajo)
    if not imagen:
        raise screen.ErrorPantalla("La captura de esa ventana salió vacía")
    # Lo que se acaba de mirar es lo que se puede tocar por coordenadas: se
    # apunta igual que con una captura de pantalla, o `devices_click` traduciría
    # contra la foto anterior.
    detalle = {
        **detalle,
        "descrita": f'la ventana «{titulo_real}»',
        "x": detalle.get("origen_x", 0),
        "y": detalle.get("origen_y", 0),
        "ancho_pantalla": detalle.get("ancho_real", 0),
        "alto_pantalla": detalle.get("alto_real", 0),
    }
    screen._recordar_mapa(detalle)
    return {"jpeg": imagen, "detalle": {**detalle, "bytes": len(imagen)}}


def _screen_capture(config: NodeConfig, arguments: dict) -> dict:
    """Fotografía una pantalla y la sube; por aquí solo vuelve el recibo.

    La imagen no cabe en la respuesta de una orden —el servidor descarta lo que
    pase de 200 KB, y una captura ronda esa cifra—, así que va por HTTP como los
    archivos. Lo que vuelve por el canal de órdenes es qué pantalla se cogió y
    cuánto ocupa, que es lo que hay que registrar.
    """
    captura_id = str(arguments.get("captura_id") or "").strip()
    if not captura_id:
        raise CapabilityError("Falta el identificador de la captura")

    try:
        if _quiere_trastienda(arguments) or arguments.get("ventana"):
            capturada = _capturar_una_ventana(arguments)
        else:
            capturada = screen.capturar(arguments.get("pantalla"))
    except screen.ErrorPantalla as error:
        raise CapabilityError(str(error)) from error

    imagen = capturada["jpeg"]
    try:
        respuesta = httpx.post(
            f"{config.url.rstrip('/')}/api/nodos/capturas/{captura_id}",
            content=imagen,
            headers={
                "Authorization": f"Bearer {config.token}",
                "Content-Type": "image/jpeg",
                "Content-Length": str(len(imagen)),
            },
            timeout=TIMEOUT_TRANSFERENCIA,
        )
    except httpx.HTTPError as error:
        raise CapabilityError(f"No pude mandar la captura: {error}") from error

    if respuesta.status_code != 200:
        raise CapabilityError(
            f"Vibi rechazó la captura ({respuesta.status_code}): "
            f"{respuesta.text[:300]}"
        )
    return capturada["detalle"]


# ---------- Ratón y teclado ----------

# Todo lo de abajo señala sobre la última captura, no sobre el escritorio: el
# modelo dice dónde pinchar mirando la imagen que se le enseñó, y `computer.py`
# traduce con el mapa que dejó esa captura. Por eso ninguna de estas
# capacidades acepta un selector de pantalla: la pantalla ya la eligió quien
# miró.
def _envolver(funcion, *args, **kwargs) -> dict:
    try:
        return funcion(*args, **kwargs)
    except computer.ErrorOrdenador as error:
        raise CapabilityError(str(error)) from error


def _screen_click(_: NodeConfig, arguments: dict) -> dict:
    modificadores = arguments.get("modificadores") or ()
    if isinstance(modificadores, str):
        modificadores = [modificadores]
    resultado = _envolver(
        computer.clic,
        arguments.get("x"),
        arguments.get("y"),
        str(arguments.get("boton") or "left"),
        arguments.get("veces") or 1,
        tuple(modificadores),
    )
    # Después del clic, porque un clic normalmente cambia el foco y lo que
    # importa saber es en qué ventana ha caído.
    return _con_destino(resultado, computer.ventana_con_foco())


def _screen_move(_: NodeConfig, arguments: dict) -> dict:
    return _envolver(computer.mover, arguments.get("x"), arguments.get("y"))


def _screen_drag(_: NodeConfig, arguments: dict) -> dict:
    return _envolver(
        computer.arrastrar,
        arguments.get("desde_x"),
        arguments.get("desde_y"),
        arguments.get("hasta_x"),
        arguments.get("hasta_y"),
        str(arguments.get("boton") or "left"),
    )


def _screen_scroll(_: NodeConfig, arguments: dict) -> dict:
    x, y = arguments.get("x"), arguments.get("y")
    return _envolver(
        computer.desplazar,
        str(arguments.get("direccion") or ""),
        arguments.get("cantidad"),
        (x, y) if x is not None and y is not None else None,
    )


def _con_destino(resultado: dict, ventana: str) -> dict:
    """Le pega a la respuesta a quién se lo ha llevado.

    El teclado no elige destino: va a la ventana que tenga el foco. Decir solo
    «hecho, 22 caracteres» deja al modelo creyendo que ha escrito donde
    quería, y ahí es donde nace el «ya está enviado» de algo que no se envió.
    """
    if isinstance(resultado, dict) and ventana:
        return {**resultado, "ventana": ventana}
    return resultado


def _screen_type(_: NodeConfig, arguments: dict) -> dict:
    # Antes de escribir, porque lo escrito puede cambiar el foco.
    destino = computer.ventana_con_foco()
    return _con_destino(
        _envolver(computer.teclear, arguments.get("texto")), destino
    )


def _screen_key(_: NodeConfig, arguments: dict) -> dict:
    destino = computer.ventana_con_foco()
    return _con_destino(
        _envolver(
            computer.pulsar, arguments.get("tecla"), arguments.get("veces") or 1
        ),
        destino,
    )


# ---------- El árbol de accesibilidad ----------

def _envolver_ui(funcion, *args, **kwargs) -> dict:
    from . import ui

    try:
        return funcion(*args, **kwargs)
    except ui.ErrorUI as error:
        raise CapabilityError(error.mensaje) from error


def _quiere_trastienda(arguments: dict) -> bool:
    return bool(arguments.get("trastienda"))


def _alli(arguments: dict, trabajo):
    """Corre `trabajo` donde toque: la trastienda o el escritorio de siempre.

    En la trastienda va por su hilo dedicado y no por un `with`, porque
    `SetThreadDesktop` se niega en cuanto el hilo tiene una ventana y UIA crea
    ventanas al primer uso. Ver `trastienda.ejecutar`.
    """
    if not _quiere_trastienda(arguments):
        return trabajo()
    from . import trastienda

    try:
        return trastienda.ejecutar(trabajo)
    except trastienda.ErrorTrastienda as error:
        raise CapabilityError(str(error)) from error


def _ui_snapshot(_: NodeConfig, arguments: dict) -> dict:
    from . import ui

    salida = _alli(
        arguments,
        lambda: _envolver_ui(
            ui.capturar,
            str(arguments.get("ventana") or "").strip() or None,
            str(arguments.get("expandir") or "").strip() or None,
        ),
    )
    if _quiere_trastienda(arguments):
        salida = {**salida, "donde": "la trastienda"}
    return salida


def _ui_batch(_: NodeConfig, arguments: dict) -> dict:
    from . import ui

    salida = _alli(
        arguments,
        lambda: _envolver_ui(
            ui.ejecutar_lote,
            arguments.get("pasos"),
            str(arguments.get("ventana") or "").strip() or None,
        ),
    )
    if _quiere_trastienda(arguments):
        salida = {**salida, "donde": "la trastienda"}
    return salida


# ---------- La trastienda ----------

def _trastienda_abrir(_: NodeConfig, arguments: dict) -> dict:
    """Abre una aplicación en el escritorio invisible.

    Es la puerta de entrada: una vez dentro, `ui.snapshot`, `ui.batch` y
    `screen.capture` saben trabajar ahí pasándoles `trastienda: true`.
    """
    from . import app_catalog, trastienda

    if not trastienda.disponible():
        raise CapabilityError(
            "Los escritorios aparte son cosa de Windows; aquí no hay trastienda."
        )

    app = str(arguments.get("app") or "").strip()
    if not app:
        raise CapabilityError("No has dicho qué abrir en la trastienda")

    # Se resuelve por el mismo catálogo que `apps.launch`, para que el nombre
    # que vale en un sitio valga en el otro.
    entrada = app_catalog.catalog.resolver(app)
    if entrada is None:
        raise CapabilityError(
            f"No encuentro «{app}» entre las aplicaciones instaladas."
        )
    if entrada.launch_kind == "packaged":
        raise CapabilityError(
            f"«{entrada.label}» es de la Microsoft Store, y ésas se abren a "
            "través del explorador: la ventana aparecería en la pantalla del "
            "usuario en vez de en la trastienda. Si tiene versión web, ábrela "
            "en un navegador de la trastienda."
        )

    objetivo = entrada.target
    resuelto = app_catalog.destino_real(objetivo)
    argumentos = ""
    if resuelto is not None:
        objetivo, argumentos = resuelto

    from . import web_apps

    extra = ""
    puerto = 0
    if web_apps.es_chromium(entrada.label):
        puerto = web_apps.reservar(entrada.label)
        extra = " " + web_apps.flag_de_depuracion(puerto)
        # Y un perfil propio, o no habrá nada que abrir: un Chromium que ya
        # está corriendo le pasa el encargo a su instancia de siempre —la del
        # escritorio del usuario— y se muere sin dejar ventana aquí. Ver
        # `web_apps.perfil_de_la_trastienda`.
        perfil = web_apps.perfil_de_la_trastienda(entrada.label)
        extra += f' --user-data-dir="{perfil}"'

    linea = f'"{objetivo}"'
    if argumentos:
        linea += f" {argumentos}"
    linea += extra

    try:
        pid = trastienda.lanzar(linea)
    except trastienda.ErrorTrastienda as error:
        if puerto:
            web_apps.olvidar(entrada.label)
        raise CapabilityError(str(error)) from error

    return {
        "app": entrada.label,
        "pid": pid,
        "donde": "la trastienda",
        **({"puerto_web": puerto} if puerto else {}),
        "aviso": (
            "Está abierta donde nadie la ve. Para mirarla o tocarla, pasa "
            "`trastienda: true` a devices_ui_snapshot, devices_ui_batch o "
            "devices_screenshot. **La ventana no se puede traer a la pantalla "
            "del usuario después**: si el resultado tiene que verse, ábrelo al "
            "final en el escritorio de siempre."
        ),
    }


def _trastienda_estado(_: NodeConfig, __: dict) -> dict:
    """Qué hay abierto en la trastienda ahora mismo."""
    from . import trastienda

    if not trastienda.disponible() or not trastienda.existe():
        return {"montada": False, "ventanas": []}

    from . import ui_windows

    def mirar():
        return [
            {"titulo": v.titulo, "handle": v.handle, "minimizada": v.minimizada}
            for v in ui_windows.ventanas()
        ]

    try:
        ventanas = trastienda.ejecutar(mirar)
    except trastienda.ErrorTrastienda as error:
        raise CapabilityError(str(error)) from error
    return {"montada": True, "ventanas": ventanas, "total": len(ventanas)}


# ---------- Aplicaciones ----------

def _web_apps(_: NodeConfig, __: dict) -> dict:
    """Con qué aplicaciones se puede hablar por dentro ahora mismo."""
    from . import web_apps

    vivas = web_apps.disponibles()
    return {
        "aplicaciones": vivas,
        "total": len(vivas),
        "aviso": (
            ""
            if vivas
            else "Ninguna ahora mismo. Una aplicación se deja hablar por "
            "dentro si la abrió Vibi, o si tiene el puerto puesto en el "
            "registro y está abierta: ciérrala y pídeme que la abra yo."
        ),
    }


def _web_evaluar(_: NodeConfig, arguments: dict) -> dict:
    """Ejecuta JavaScript dentro de una pestaña, sin ponerla delante."""
    from . import cdp, web_apps

    app = str(arguments.get("app") or "").strip()
    javascript = str(arguments.get("javascript") or "").strip()
    if not javascript:
        raise CapabilityError("No has dicho qué ejecutar")

    puerto = arguments.get("puerto")
    puerto = int(puerto) if puerto else web_apps.puerto_de(app)
    if not puerto:
        vivas = ", ".join(v["app"] for v in web_apps.disponibles()) or "ninguna"
        raise CapabilityError(
            f"No sé por dónde hablar con «{app}». Ahora mismo se puede con: "
            f"{vivas}. Una aplicación escucha si la abrió Vibi, o si tiene "
            "el puerto puesto en el registro y está abierta."
        )

    async def trabajo():
        return await cdp.evaluar_en(
            puerto, str(arguments.get("pestana") or "").strip() or None, javascript
        )

    try:
        valor, pagina = _en_bucle(trabajo())
    except cdp.ErrorCDP as error:
        raise CapabilityError(str(error)) from error

    return {
        "resultado": _recortar_resultado(valor),
        "pestana": pagina.get("title", ""),
        "url": pagina.get("url", ""),
        "app": app or "el navegador",
    }


# Lo que cabe de vuelta. Una página entera no cabe por el canal de órdenes
# (`nodes.MAX_RESULT_BYTES`), y traérsela para que se corte por la mitad es
# gastar el viaje: mejor decir que se ha recortado.
MAX_RESULTADO_WEB = 40_000


def _recortar_resultado(valor: object) -> object:
    if not isinstance(valor, str) or len(valor) <= MAX_RESULTADO_WEB:
        return valor
    return (
        valor[:MAX_RESULTADO_WEB]
        + f"\n… (recortado, eran {len(valor)} caracteres)"
    )


def _en_bucle(corrutina):
    """Corre una corrutina desde un handler síncrono, haya bucle o no."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(corrutina)
    # Ya hay bucle en este hilo: se corre en otro para no reentrar.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, corrutina).result()


def _apps_launch(_: NodeConfig, arguments: dict) -> dict:
    app = str(arguments.get("app") or "").strip()
    if not app:
        raise CapabilityError("Falta la aplicación que quieres abrir")
    return app_catalog.catalog.launch(app)


def _inventario_mapa(_: NodeConfig, arguments: dict) -> dict:
    """Construye un retrato del equipo: carpetas por extensión, sin revelar contenido."""
    raices_crudo = arguments.get("raices")
    if not raices_crudo:
        raise CapabilityError("Falta la lista de directorios para escanear")

    raices = []
    if isinstance(raices_crudo, list):
        for ruta in raices_crudo:
            path = Path(str(ruta or "").strip()).expanduser()
            raices.append(path)
    else:
        path = Path(str(raices_crudo).strip()).expanduser()
        raices = [path]

    if not raices:
        raise CapabilityError("No hay directorios válidos para escanear")

    return inventario.mapa_de(raices)


HANDLERS = {
    "ping": _ping,
    "projects.list": _list_projects,
    "shell.run": _shell_run,
    "shell.status": _shell_status,
    "shell.stop": _shell_stop,
    "browser.open": _browser_open,
    "browser.mcp": _browser_mcp,
    "system.mcp": _system_mcp,
    "apps.launch": _apps_launch,
    "trastienda.abrir": _trastienda_abrir,
    "trastienda.estado": _trastienda_estado,
    "web.apps": _web_apps,
    "web.evaluar": _web_evaluar,
    "open.path": _open_path,
    "files.search": _files_search,
    "files.stat": _files_stat,
    "files.push": _files_push,
    "files.pull": _files_pull,
    "inventario.mapa": _inventario_mapa,
    "media.control": _media_control,
    "media.now_playing": _media_now_playing,
    "screen.capture": _screen_capture,
    "screen.click": _screen_click,
    "screen.move": _screen_move,
    "screen.drag": _screen_drag,
    "screen.scroll": _screen_scroll,
    "screen.type": _screen_type,
    "screen.key": _screen_key,
    "ui.snapshot": _ui_snapshot,
    "ui.batch": _ui_batch,
}


# Las que no existen en todas las máquinas. Declararlas donde no funcionan es
# prometerle al modelo algo que va a fallar cuando lo intente, y el modelo no
# tiene forma de saberlo antes.
CAPACIDADES_CONDICIONALES = frozenset({"ui.snapshot", "ui.batch"})


def disponibles() -> list[str]:
    """Lo que esta máquina puede hacer de verdad, para el saludo al servidor."""
    from . import ui

    hay_arbol = ui.disponible()
    return sorted(
        nombre
        for nombre in HANDLERS
        if hay_arbol or nombre not in CAPACIDADES_CONDICIONALES
    )


def run(config: NodeConfig, capability: str, arguments: dict) -> dict:
    handler = HANDLERS.get(capability)
    if handler is None:
        raise CapabilityError(f"Este dispositivo no sabe hacer «{capability}»")
    return handler(config, arguments or {})

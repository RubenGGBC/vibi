"""Qué aplicaciones de este ordenador se dejan hablar por dentro, y dónde.

Casi todo el escritorio moderno es Chromium con un marco alrededor. Medido en
esta máquina el 2026-08-20: Discord y VS Code son Electron, WhatsApp y Raycast
son WebView2, Spotify es CEF, Opera es Opera. Todos hablan el protocolo de las
herramientas de desarrollo, y por él se les puede preguntar y mandar hacer
cosas **sin ponerles la ventana delante** — ver `cdp`.

Este módulo es la agenda: qué aplicación escucha en qué puerto. Hay dos formas
de acabar en ella:

* **El navegador de Vibi**, que ya se lanza con el flag desde `navegador_real`
  y siempre está en el mismo puerto.
* **Las que lanza Vibi**, a las que `apps.launch` les añade el flag y les
  reserva un puerto. Se apunta aquí para poder encontrarlas después.

* **Las que abren el puerto solas.** Una aplicación WebView2 con la política
  del registro puesta arranca ya escuchando, la lance quien la lance —también
  el usuario desde su menú de inicio—, y deja escrito en qué puerto. Se
  encuentran con `descubrir_webview2()` y no hacen falta en la agenda. Ver
  `docs/puerto-de-depuracion.md`.

**Una aplicación que ya estaba abierta y no entra en ninguno de esos tres
casos no aparece**: el puerto se abre al arrancar el proceso y no después. Lo
honesto es decirlo —«ciérrala y la abro yo»— en vez de fingir que no se puede
hablar con ella nunca.
"""
from __future__ import annotations

import threading

from . import cdp

# El del navegador que Vibi ya lanza con depuración. Va aquí para que aparezca
# en la agenda como una más: quien pregunta «con qué puedo hablar» tiene que
# verlo sin saber que es un caso especial.
PUERTO_NAVEGADOR = 9333

# Desde dónde se reparten puertos a las demás. Por encima de los que usan el
# navegador (9333) y los servidores MCP del nodo (8931, 8933), y por debajo del
# rango efímero de Windows.
PRIMER_PUERTO = 9350
ULTIMO_PUERTO = 9399

# Las que sabemos que son Chromium por dentro y aceptan el flag. La lista es
# por prudencia y no por capricho: añadirle el flag a algo que no es Chromium
# le pasa un argumento que no entiende, y hay programas que se niegan a
# arrancar con un argumento desconocido.
#
# La clave es un trozo del nombre normalizado de la aplicación.
CHROMIUM_CONOCIDAS = (
    # Los navegadores primero, que en la trastienda son lo más útil: un
    # navegador ahí dentro con la sesión iniciada resuelve todas las webs de
    # golpe —WhatsApp Web incluida— sin depender de la aplicación de escritorio.
    "opera",
    "chrome",
    "edge",
    "brave",
    "vivaldi",
    "chromium",
    "discord",
    "slack",
    "code",          # VS Code y sus variantes
    "notion",
    "obsidian",
    "spotify",
    "figma",
    "teams",
    "signal",
    "element",
    "postman",
    "insomnia",
    "whatsapp",
)

_candado = threading.Lock()
# nombre normalizado -> puerto
_agenda: dict[str, int] = {}


def es_chromium(nombre: str) -> bool:
    """Si esa aplicación es de las que se dejan hablar por dentro."""
    plano = " ".join(str(nombre or "").casefold().split())
    if not plano:
        return False
    return any(marca in plano for marca in CHROMIUM_CONOCIDAS)


def flag_de_depuracion(puerto: int) -> str:
    return f"--remote-debugging-port={puerto}"


def perfil_de_la_trastienda(nombre: str) -> str:
    """Dónde guarda sus cosas un navegador de la trastienda.

    **Sin un perfil propio no hay navegador en la trastienda.** Un Chromium que
    ya está abierto no arranca otra vez: el segundo proceso le pasa el encargo
    al primero por un socket del perfil y se muere. Medido el 2026-08-20 —
    lanzar Opera en la trastienda con Opera ya abierto no creó ninguna ventana
    ahí dentro y no abrió ningún puerto—. Con `--user-data-dir` distinto son
    dos navegadores que no se conocen, y el de la trastienda es de Vibi.

    El precio es que ese perfil empieza **sin sesiones iniciadas**: hay que
    entrar una vez en lo que se vaya a usar. Es un pago único y a cambio deja
    de depender de que el usuario tenga su navegador abierto o cerrado.
    """
    import os
    from pathlib import Path

    limpio = "".join(
        c if c.isalnum() else "-" for c in str(nombre or "vibi").casefold()
    ).strip("-") or "vibi"
    base = Path(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"))
    return str(base / "Vibi" / "trastienda" / limpio)


def _puerto_libre() -> int:
    """Uno que no esté ya repartido ni ocupado por nadie."""
    from .browser_mcp import escuchando

    repartidos = set(_agenda.values())
    for puerto in range(PRIMER_PUERTO, ULTIMO_PUERTO + 1):
        if puerto in repartidos:
            continue
        if not escuchando(puerto, timeout=0.15):
            return puerto
    raise RuntimeError("No quedan puertos libres para hablar con aplicaciones")


def reservar(nombre: str) -> int:
    """Aparta un puerto para esa aplicación y lo devuelve.

    Si ya tenía uno se reutiliza: relanzar Discord no debería dejar la agenda
    con dos entradas suyas apuntando a sitios distintos.
    """
    clave = " ".join(str(nombre or "").casefold().split())
    with _candado:
        if clave in _agenda:
            return _agenda[clave]
        puerto = _puerto_libre()
        _agenda[clave] = puerto
        return puerto


def olvidar(nombre: str) -> None:
    clave = " ".join(str(nombre or "").casefold().split())
    with _candado:
        _agenda.pop(clave, None)


def puerto_de(nombre: str) -> int | None:
    """Dónde escucha esa aplicación, si es que escucha en algún sitio."""
    clave = " ".join(str(nombre or "").casefold().split())
    if not clave:
        return None
    if clave in ("navegador", "opera", "chrome", "el navegador"):
        return PUERTO_NAVEGADOR
    with _candado:
        if clave in _agenda:
            return _agenda[clave]
        # Por trozos, que es como la nombra una persona: «vs code» contra
        # «visual studio code».
        for guardado, puerto in _agenda.items():
            if clave in guardado or guardado in clave:
                return puerto
    # Y si Vibi no la lanzó, puede haber abierto el puerto ella sola. La
    # agenda va antes a propósito: si Vibi la lanzó, ese es el puerto que
    # repartió y el que sabe que sigue siendo suyo.
    descubiertas = descubrir_webview2()
    if clave in descubiertas:
        return descubiertas[clave]
    for nombre, puerto in descubiertas.items():
        if clave in nombre or nombre in clave:
            return puerto
    return None


# Lo que WebView2 deja escrito bajo la carpeta de cada aplicación cuando
# arranca con el puerto abierto: el puerto en la primera línea y la ruta del
# WebSocket del navegador en la segunda.
RASTRO_WEBVIEW2 = ("LocalCache", "EBWebView", "DevToolsActivePort")


def _nombre_de_paquete(carpeta: str) -> str:
    """`5319275A.WhatsAppDesktop_cv1g1gvanyjgm` → `whatsappdesktop`.

    Ni el editor de delante ni el hash de detrás dicen nada de qué aplicación
    es. Lo que queda en medio sí, y es lo que `puerto_de` sabe buscar por
    trozos cuando alguien la nombra «whatsapp» a secas.
    """
    ultimo = str(carpeta or "").split(".")[-1]
    return ultimo.split("_")[0].casefold()


def _contesta_un_chromium(puerto: int, timeout: float = 0.4) -> bool:
    """Si en ese puerto hay de verdad un Chromium y no otra cosa.

    **Esto es una comprobación de seguridad, no una de salud.** El puerto no lo
    decidimos nosotros: lo leemos de un archivo que vive en el perfil del
    usuario y que cualquier proceso suyo puede reescribir. Seguirlo a ciegas
    sería aceptar que nos manden a hablarle a otro servicio de la máquina —una
    base de datos, una API interna— y encima con Vibi de mensajero.

    Se exige que conteste el `/json/version` de las herramientas de desarrollo
    con las dos señas que solo tiene un CDP de verdad. Un servicio cualquiera
    responderá otra cosa, o nada.
    """
    import json as _json
    import urllib.request

    try:
        peticion = urllib.request.Request(
            f"http://127.0.0.1:{puerto}/json/version",
            headers={"Host": f"127.0.0.1:{puerto}"},
        )
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            datos = _json.loads(respuesta.read().decode("utf-8", "replace"))
    except Exception:
        return False
    return bool(
        isinstance(datos, dict)
        and datos.get("Browser")
        and datos.get("webSocketDebuggerUrl")
    )


def _raices_de_paquetes() -> list:
    """Dónde guardan sus cosas las aplicaciones de la Store."""
    import os
    from pathlib import Path

    base = os.environ.get("LOCALAPPDATA")
    return [Path(base) / "Packages"] if base else []


def descubrir_webview2(raices: list | None = None) -> dict:
    """Las aplicaciones WebView2 que ya tienen su puerto abierto.

    **Esta es la puerta que no depende de que la abriera Vibi.** Una aplicación
    con la política del registro puesta —ver `docs/puerto-de-depuracion.md`—
    arranca con el puerto abierto la lance quien la lance, también el usuario
    desde su menú de inicio, y deja escrito cuál en su `DevToolsActivePort`.
    Hasta ahora `disponibles()` solo sabía de las que había lanzado Vibi, que
    es justo lo que hacía caer a WhatsApp al árbol de accesibilidad.

    El puerto es efímero a propósito: uno fijo es adivinable por cualquiera que
    pruebe los de siempre, y este no se sabe hasta leerlo.
    """
    from pathlib import Path

    encontradas: dict[str, int] = {}
    for raiz in raices if raices is not None else _raices_de_paquetes():
        try:
            paquetes = sorted(Path(raiz).iterdir())
        except OSError:
            continue
        for paquete in paquetes:
            rastro = paquete.joinpath(*RASTRO_WEBVIEW2)
            try:
                primera = rastro.read_text("utf-8").splitlines()[0].strip()
                puerto = int(primera)
            except (OSError, ValueError, IndexError):
                continue
            # Un puerto que no existe no se prueba siquiera.
            if not 1 <= puerto <= 65535:
                continue
            if not _contesta_un_chromium(puerto):
                continue
            encontradas[_nombre_de_paquete(paquete.name)] = puerto
    return encontradas


def disponibles() -> list[dict]:
    """Con qué se puede hablar ahora mismo, comprobándolo de verdad.

    Se prueba cada puerto en vez de fiarse de la agenda: una aplicación que se
    cerró sigue apuntada y contestaría que sí. Es la misma lección que con los
    servidores MCP — lo que manda es el puerto, no la variable.
    """
    with _candado:
        candidatos = [("el navegador", PUERTO_NAVEGADOR)] + [
            (nombre, puerto) for nombre, puerto in _agenda.items()
        ]
    # Las que abren el puerto solas no están en la agenda y cuentan igual.
    apuntados = {puerto for _, puerto in candidatos}
    for nombre, puerto in descubrir_webview2().items():
        if puerto not in apuntados:
            candidatos.append((nombre, puerto))

    vivos = []
    for nombre, puerto in candidatos:
        try:
            paginas = cdp.pestanas(puerto)
        except cdp.ErrorCDP:
            continue
        vivos.append({
            "app": nombre,
            "puerto": puerto,
            "pestanas": [
                {"titulo": p.get("title", ""), "url": p.get("url", "")}
                for p in paginas[:12]
            ],
        })
    return vivos

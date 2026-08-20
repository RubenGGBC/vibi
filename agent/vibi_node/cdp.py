"""Hablar con una pestaña de Chromium directamente, sin tocar la pantalla.

Esta es la puerta que faltaba, y es más general de lo que parece: **casi todo
el escritorio moderno es Chromium por dentro**. Comprobado en esta máquina el
2026-08-20 — Discord y VS Code son Electron, WhatsApp y Raycast son WebView2,
Spotify es CEF, y el navegador es el navegador. Todos hablan el mismo
protocolo, el de las herramientas de desarrollo, y todos aceptan que se les
pregunte y se les mande hacer cosas **con su ventana detrás, minimizada o
tapada**, porque no pasa por el ratón ni por el teclado ni por el foco.

Lo que se gana frente a manejar la ventana:

* **No le tapa la pantalla a nadie.** Ninguna orden necesita primer plano.
* **Es rápido.** Una evaluación son unos milisegundos, contra los cientos que
  cuesta leer un árbol de accesibilidad y los segundos de una captura.
* **Y no hay que adivinar.** El DOM dice qué es cada cosa; no hay que deducir
  de un rectángulo si eso era un botón.

Lo que **no** cubre: una aplicación que no sea Chromium —un instalador, un
diálogo de Windows, un juego, Qt, WPF—. Para eso sigue estando el árbol de
accesibilidad, que es lo genérico. Esto es el atajo bueno cuando existe.

**Un Chromium solo acepta esto si arrancó con `--remote-debugging-port`.** El
navegador de Vibi ya lo hace (`navegador_real`), y para las demás aplicaciones
hay que lanzarlas con el mismo flag: ver `app_catalog`. Sin el flag no hay
puerto y no hay conversación, y eso no se puede arreglar desde fuera.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

# Cuánto se espera a que el puerto conteste la lista de pestañas. Es local y
# contesta en milisegundos; esto es la red para cuando el proceso está
# atascado, no un margen de trabajo.
TIMEOUT_LISTA = 2.0

# Y cuánto puede tardar una evaluación. Más generoso porque el JavaScript lo
# ejecuta la página, y una página cargando puede tardar en atender.
TIMEOUT_EVALUAR = 8.0


class ErrorCDP(Exception):
    """Algo que impide hablar con la pestaña, dicho para que se entienda."""


def _normalizar(texto: str) -> str:
    """La misma que usa el árbol de accesibilidad, y por el mismo motivo.

    Quien dice «ponme el video de musica» no está escribiendo el título, lo
    está recordando. Un acento de más o de menos no puede decidir si se
    encuentra la pestaña.
    """
    from . import ui_tree

    return ui_tree.normalizar(str(texto or ""))


def pestanas(puerto: int, host: str = "127.0.0.1") -> list[dict]:
    """Las pestañas y ventanas que ese Chromium tiene abiertas.

    Solo las de tipo `page`: un Chromium publica también sus trabajadores de
    servicio, sus extensiones y sus iframes desgajados, y ninguno de esos es un
    sitio donde alguien esté mirando algo.
    """
    url = f"http://{host}:{puerto}/json/list"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_LISTA) as respuesta:
            crudo = json.loads(respuesta.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise ErrorCDP(
            f"No contesta nadie en el puerto {puerto}. Esa aplicación no se "
            "abrió con la depuración activada, o ya no está."
        ) from error
    except json.JSONDecodeError as error:
        raise ErrorCDP(
            f"El puerto {puerto} contesta, pero no es un Chromium."
        ) from error

    if not isinstance(crudo, list):
        return []
    return [
        p
        for p in crudo
        if isinstance(p, dict)
        and p.get("type") == "page"
        and p.get("webSocketDebuggerUrl")
    ]


def elegir(paginas: list[dict], pista: str | None) -> dict:
    """Cuál de las pestañas es la que se pide, o la única si no hay duda.

    Se busca en el título y en la URL, porque una persona señala una pestaña de
    las dos formas: «la de YouTube» y «el vídeo de Blue Lock» son igual de
    válidas. Sin pista, solo vale si hay exactamente una: elegir por el usuario
    entre varias es como se acaba pausando el vídeo que no era.
    """
    if not paginas:
        raise ErrorCDP("No hay ninguna pestaña abierta ahí.")

    if not pista or not pista.strip():
        if len(paginas) == 1:
            return paginas[0]
        titulos = ", ".join(f'"{p.get("title", "")[:40]}"' for p in paginas[:6])
        raise ErrorCDP(
            f"Hay {len(paginas)} pestañas y no has dicho cuál: {titulos}. "
            "Di un trozo de su título o de su dirección."
        )

    buscado = _normalizar(pista)
    exactas = [p for p in paginas if _normalizar(p.get("title")) == buscado]
    if len(exactas) == 1:
        return exactas[0]

    parciales = [
        p
        for p in paginas
        if buscado in _normalizar(p.get("title"))
        or buscado in _normalizar(p.get("url"))
    ]
    if len(parciales) == 1:
        return parciales[0]
    if not parciales:
        titulos = ", ".join(f'"{p.get("title", "")[:40]}"' for p in paginas[:6])
        raise ErrorCDP(
            f"No hay ninguna pestaña que hable de «{pista}». Abiertas: {titulos}."
        )
    titulos = ", ".join(f'"{p.get("title", "")[:40]}"' for p in parciales[:6])
    raise ErrorCDP(
        f"«{pista}» casa con {len(parciales)} pestañas: {titulos}. Afina."
    )


async def evaluar(pagina: dict, javascript: str) -> object:
    """Ejecuta ese JavaScript dentro de la pestaña y devuelve lo que dé.

    Es una conversación de dos mensajes por el WebSocket que el propio Chromium
    publica para cada pestaña. Se abre y se cierra en cada llamada a propósito:
    mantenerla viva obligaría a vigilar reconexiones y a saber cuándo muere una
    pestaña, y abrirla cuesta un par de milisegundos contra localhost.

    `awaitPromise` va puesto porque casi todo lo interesante de una página
    devuelve una promesa —`video.play()` sin ir más lejos—, y sin esperarla se
    contestaría «hecho» antes de que pasara nada. Que es justo el tipo de
    mentira que hay que evitar.
    """
    import websockets

    socket_url = pagina.get("webSocketDebuggerUrl")
    if not socket_url:
        raise ErrorCDP("Esa pestaña no admite que se le hable.")

    peticion = json.dumps({
        "id": 1,
        "method": "Runtime.evaluate",
        "params": {
            "expression": javascript,
            "returnByValue": True,
            "awaitPromise": True,
            # Sin esto, una página con `Content-Security-Policy` estricta
            # rechaza la evaluación: YouTube es una de ellas.
            "userGesture": True,
        },
    })

    try:
        async with websockets.connect(
            socket_url, open_timeout=TIMEOUT_EVALUAR, max_size=8 * 1024 * 1024
        ) as conexion:
            await conexion.send(peticion)
            while True:
                crudo = await conexion.recv()
                mensaje = json.loads(crudo)
                # Por el mismo socket llegan eventos que no hemos pedido; lo
                # nuestro es lo que trae nuestro `id`.
                if mensaje.get("id") == 1:
                    break
    except ErrorCDP:
        raise
    except Exception as error:
        raise ErrorCDP(
            f"Se cortó la conversación con la pestaña: {type(error).__name__}"
        ) from error

    if "error" in mensaje:
        detalle = mensaje["error"].get("message", "sin detalle")
        raise ErrorCDP(f"La pestaña rechazó la orden: {detalle}")

    resultado = mensaje.get("result", {})
    excepcion = resultado.get("exceptionDetails")
    if excepcion:
        texto = (
            excepcion.get("exception", {}).get("description")
            or excepcion.get("text")
            or "sin detalle"
        )
        raise ErrorCDP(f"El código falló dentro de la página: {texto}")

    return resultado.get("result", {}).get("value")


async def evaluar_en(
    puerto: int, pista: str | None, javascript: str, host: str = "127.0.0.1"
) -> tuple[object, dict]:
    """Lo de arriba, resolviendo antes qué pestaña es. Devuelve `(valor, pestaña)`."""
    pagina = elegir(pestanas(puerto, host), pista)
    return await evaluar(pagina, javascript), pagina

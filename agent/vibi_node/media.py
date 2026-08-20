"""Qué suena en esta máquina y cómo mandarle callar.

Cada sistema tiene su propio mecanismo, igual que pasa con abrir un enlace:

* **Windows** expone las sesiones multimedia del sistema, las mismas que mueven
  las teclas de play del teclado. Da órdenes explícitas —reanudar y pausar son
  cosas distintas— y además dice qué se está reproduciendo.
* **Linux** tiene MPRIS sobre D-Bus, que da lo mismo.
* **macOS** no tiene equivalente público y habría que ir por AppleScript,
  aplicación por aplicación.

De momento solo está escrito Windows. Los otros dos caen en un error que dice
exactamente eso, en vez de fallar de una forma que haya que adivinar: la
frontera está puesta para que añadirlos sea escribir una función.

Un límite medido, no supuesto: **el navegador expone una sola sesión para todas
sus pestañas**, cuyos metadatos saltan al vídeo que esté activo. Aquí no se
controla una pestaña concreta, se controla lo que suena. Por eso las órdenes
pueden apuntar a un título: es la única forma de asegurarse de que el play va al
vídeo recién abierto y no al Spotify que tenías de fondo.

Y un segundo límite, más duro, medido en Zen (Firefox) sobre Windows 11: **una
pestaña que todavía no suena no existe para el sistema**. Se abrieron dos
vídeos nuevos y durante cuarenta segundos la sesión del navegador siguió
anclada al vídeo anterior, pausado. Buscar el vídeo recién abierto por título
no podía funcionar nunca —y el play acababa reanudando el de antes—, así que
para arrancarlo hay que salir de aquí: mirar qué ventana tiene delante ese
vídeo y darle al play como lo haría una persona, con el teclado. Está en
`_arrancar_pestana`.

De esos dos límites juntos sale la regla que ordena el resto: como solo hay una
sesión para todo el navegador, **solo puede sonar una cosa a la vez** si se
quiere que las órdenes lleguen a donde miras. Abrir una pestaña no pausa la
anterior, así que lo hace `_callar_lo_anterior` antes de arrancar la nueva. Sin
eso sonaban dos vídeos y el «pausa» siguiente iba al que el navegador decidiera.

Última trampa, para quien venga a depurar esto: **los metadatos van retrasados
unos cuatro segundos**. Justo después de arrancar un vídeo, el sistema contesta
con el título del anterior y el estado del nuevo. No está roto; es que aún no
se ha enterado. Medirlo demasiado pronto es lo que hace parecer que el arreglo
no funciona.
"""
from __future__ import annotations

import asyncio
import ctypes
import platform
import re
import time
from dataclasses import dataclass

ACCIONES = ("play", "pause", "next", "previous")

# Cuánto esperar a que la pestaña recién abierta sea la que se está viendo.
# Medido en Windows 11 con Zen: la ventana toma el foco a 1,3 s y la barra de
# título pasa a hablar del vídeo nuevo a 3,3 s. El resto es margen para una
# máquina cargada o una red lenta; no es un coste fijo, porque en cuanto la
# pestaña aparece se deja de esperar.
ESPERA_SESION = 12.0
INTERVALO_SONDEO = 0.3

# Cuánto se mira si el vídeo ya aparece sonando después de darle al play. Es
# para rellenar la respuesta, no para decidir si funcionó: medido en Zen, el
# audio empieza al instante pero la sesión tarda unos cinco segundos en
# publicarse. Tratar ese retraso como un fracaso haría que Vibi te dijera
# «dale tú» con la canción ya sonando.
CONFIRMACION = 1.5

# Los navegadores se identifican con un hash opaco («F0DC299D809B9700»), no con
# su nombre. Enseñártelo sería peor que callar.
IDENTIFICADOR_OPACO = re.compile(r"^[0-9A-F]{8,}$", re.IGNORECASE)

# El companion de Vibi corre sobre WebView2, y su voz registra una sesión
# multimedia como cualquier reproductor. Mientras habla, Windows la considera
# «la sesión actual», así que un «pausa» a secas la callaba a ella en vez de a
# la música. Nunca es la respuesta a una orden de reproducción.
APPS_QUE_NO_SON_REPRODUCTORES = frozenset({"msedgewebview2.exe"})


class MediaError(Exception):
    pass


@dataclass(frozen=True)
class Sonando:
    titulo: str | None
    artista: str | None
    app: str | None
    sonando: bool

    def como_dict(self) -> dict:
        return {
            "titulo": self.titulo,
            "artista": self.artista,
            "app": self.app,
            "sonando": self.sonando,
        }


def _normalizar(texto: str | None) -> str:
    return " ".join(str(texto or "").split()).casefold()


def coincide(titulo_sesion: str | None, buscado: str | None) -> bool:
    """¿Habla esta sesión del mismo vídeo?

    Por contención en los dos sentidos: YouTube recorta títulos largos y
    nosotros ya recortamos a 120 caracteres al resolverlos, así que exigir
    igualdad exacta fallaría justo con los títulos más largos.
    """
    izquierda, derecha = _normalizar(titulo_sesion), _normalizar(buscado)
    if not izquierda or not derecha:
        return False
    return izquierda in derecha or derecha in izquierda


def habla_de(titulo_ventana: str | None, buscado: str | None) -> bool:
    """¿La ventana que se está viendo tiene delante este vídeo?

    Aquí sí se exige contención en un solo sentido: la barra de título del
    navegador es el título del vídeo más su propia coletilla («… - YouTube —
    Zen Browser»), nunca al revés. Aceptar el sentido contrario, como hace
    `coincide`, haría que una ventana llamada «YouTube» a secas valiera por
    cualquier vídeo, y la pulsación acabaría en la pestaña equivocada.
    """
    izquierda, derecha = _normalizar(titulo_ventana), _normalizar(buscado)
    if not izquierda or not derecha:
        return False
    return derecha in izquierda


def _app_legible(identificador: str | None) -> str | None:
    if not identificador or IDENTIFICADOR_OPACO.fullmatch(identificador):
        return None
    return identificador


def _es_reproductor(sesion) -> bool:
    return (
        str(sesion.source_app_user_model_id or "").lower()
        not in APPS_QUE_NO_SON_REPRODUCTORES
    )


# ---------- La pestaña que se está viendo ----------

# La «k» es el atajo de play/pausa de YouTube y funciona en toda la página, sin
# depender de que el foco esté dentro del reproductor como le pasa al espacio.
VK_K = 0x4B
KEYEVENTF_KEYUP = 0x0002


def _texto_de_ventana(ventana) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(ventana, buffer, len(buffer))
    return buffer.value


def _ventana_del_video(titulo: str):
    """La ventana que tiene delante este vídeo, mirándolas todas.

    Se enumeran en vez de preguntar por la que tiene el foco, y no por gusto:
    cuando el navegador ya está abierto, pasarle una URL desde fuera arranca un
    segundo proceso que le entrega el enlace a través de una ventana oculta sin
    título. Esa ventana fantasma se queda con el primer plano un rato variable
    —medido entre 0,2 y más de 1,5 segundos—, así que preguntar por el foco
    devolvía una ventana vacía justo cuando la de verdad ya tenía el vídeo.

    El título de la ventana es la única pista que distingue una pestaña de
    otra: las sesiones multimedia no las separan y no hay API que las enumere.
    """
    encontrada = []

    def visitar(ventana, _):
        if ctypes.windll.user32.IsWindowVisible(ventana) and habla_de(
            _texto_de_ventana(ventana), titulo
        ):
            encontrada.append(ventana)
            return False
        return True

    try:
        # El prototipo se construye aquí porque `WINFUNCTYPE` solo existe en
        # Windows: a nivel de módulo reventaría al importar en cualquier otro
        # sistema, y este archivo tiene que poder leerse en todos.
        prototipo = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p
        )
        ctypes.windll.user32.EnumWindows(prototipo(visitar), 0)
    except (AttributeError, OSError):
        return None
    return encontrada[0] if encontrada else None


def _traer_al_frente(ventana) -> bool:
    """Pone esa ventana delante, y dice si de verdad se ha quedado delante.

    La respuesta importa más que la acción: la tecla va a donde esté el foco,
    así que sin la confirmación estaríamos escribiendo a ciegas. Windows puede
    negar el cambio a un proceso de fondo, y entonces lo correcto es no pulsar.
    """
    try:
        user32 = ctypes.windll.user32
        if user32.GetForegroundWindow() == ventana:
            return True
        user32.SetForegroundWindow(ventana)
        time.sleep(0.1)
        return user32.GetForegroundWindow() == ventana
    except (AttributeError, OSError):
        return False


def _pulsar_play_pausa() -> None:
    """Le da al play a la pestaña que se está viendo, como haría una persona.

    Es un interruptor, no un play: pulsar dos veces deja el vídeo como estaba.
    Por eso quien llama comprueba antes si ya suena y no reintenta a ciegas.
    """
    user32 = ctypes.windll.user32
    user32.keybd_event(VK_K, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_K, 0, KEYEVENTF_KEYUP, 0)


# ---------- Windows ----------

def _cargar_windows():
    """Importa la API de Windows solo cuando toca.

    Va aquí dentro y no arriba del módulo a propósito: un Mac no tiene este
    paquete y no debe reventar al importar el archivo por algo que jamás usará.
    """
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Estado,
        )
    except ImportError as error:
        raise MediaError(
            "A este dispositivo le falta el paquete de control multimedia. "
            "Instálalo con: pip install winrt-Windows.Media.Control"
        ) from error
    return Manager, Estado


async def _describir(sesion, Estado) -> Sonando:
    try:
        propiedades = await sesion.try_get_media_properties_async()
        titulo, artista = propiedades.title, propiedades.artist
    except OSError:
        # Una sesión puede morir entre que la enumeramos y la interrogamos.
        titulo = artista = None
    return Sonando(
        titulo=titulo or None,
        artista=artista or None,
        app=_app_legible(sesion.source_app_user_model_id),
        sonando=sesion.get_playback_info().playback_status == Estado.PLAYING,
    )


async def _listar(manager, Estado) -> list[tuple[object, Sonando]]:
    return [
        (sesion, await _describir(sesion, Estado))
        for sesion in manager.get_sessions()
    ]


async def _elegir(manager, Estado, titulo: str | None):
    """La sesión a la que va la orden.

    Con título, la que hable de ese vídeo y solo esa: mandar un play a ciegas
    podría arrancar algo que habías dejado pausado a propósito. Sin título, la
    que el sistema considere actual, que es lo que quieres decir cuando dices
    «pausa» sin más —salvo cuando la actual es la propia Vibi hablando, que
    entonces se busca detrás de ella lo que de verdad estás escuchando.
    """
    if titulo is None:
        return await _lo_que_de_verdad_suena(manager, Estado)
    for sesion, descripcion in await _listar(manager, Estado):
        if coincide(descripcion.titulo, titulo) and _es_reproductor(sesion):
            return sesion
    return None


async def _lo_que_de_verdad_suena(manager, Estado):
    """A qué se refiere una orden sin título.

    No se le pregunta al sistema cuál es «la sesión actual», porque miente de
    dos formas medidas en esta máquina: mientras Vibi habla contesta que la
    actual es ella, y con varias pestañas que han sonado contesta una que está
    pausada aunque otra esté sonando. Un «pausa» acababa callando a Vibi o
    pausando lo ya pausado, con la música siguiendo.

    Así que se busca lo que está en marcha, que es lo que quieres decir con
    «pausa» o «siguiente». Solo si no suena nada se acepta la sesión actual,
    que entonces sí es la respuesta buena: es la que un «play» reanudaría.
    """
    reproductores = [
        (sesion, descripcion)
        for sesion, descripcion in await _listar(manager, Estado)
        if _es_reproductor(sesion)
    ]

    for sesion, descripcion in reproductores:
        if descripcion.sonando:
            return sesion

    actual = manager.get_current_session()
    if actual is not None and _es_reproductor(actual):
        return actual
    return reproductores[0][0] if reproductores else None


async def _suena(manager, Estado, titulo: str) -> bool:
    for sesion, descripcion in await _listar(manager, Estado):
        if coincide(descripcion.titulo, titulo) and _es_reproductor(sesion):
            return descripcion.sonando
    return False


async def _callar_lo_anterior(manager, Estado, titulo: str) -> None:
    """Pausa lo que estuviera sonando antes de poner el vídeo nuevo.

    No es cortesía, es lo que hace que el resto funcione. Abrir una pestaña no
    pausa la anterior, así que sin esto acabas oyendo dos cosas a la vez; y
    como el navegador publica **una sola sesión** para todas sus pestañas, con
    dos sonando el «pausa» siguiente iba a parar a la que él considerase
    activa, que era justo la vieja. Dejando sonando una sola, la sesión habla
    de ella y las órdenes van a donde miras.

    Un fallo aquí no cancela nada: si algo se resiste a callarse, peor es no
    llegar a poner lo que pediste.
    """
    for sesion, descripcion in await _listar(manager, Estado):
        if not descripcion.sonando or not _es_reproductor(sesion):
            continue
        if coincide(descripcion.titulo, titulo):
            continue
        try:
            await sesion.try_pause_async()
        except OSError:
            pass


async def _arrancar_pestana(manager, Estado, titulo: str, espera: float) -> bool:
    """Le da al play a un vídeo que todavía no existe para el sistema.

    Un vídeo recién abierto no aparece entre las sesiones hasta que suena, así
    que no hay a quién mandarle la orden: hay que esperar a que su pestaña sea
    la que se está viendo y pulsar la tecla, que va a donde está el foco.

    Dos cautelas que no son opcionales. Se comprueba en cada vuelta si el vídeo
    arrancó solo, porque entonces pulsar lo pausaría —justo lo contrario de lo
    que pediste—. Y no se pulsa hasta confirmar que la ventana del vídeo está
    delante de verdad: si estabas escribiendo en otra cosa, la «k» acabaría
    dentro de tu documento. Quedarse sin arrancar es un mal menor frente a
    teclear en la ventana de otro; el vídeo está abierto igual y le puedes dar
    tú.
    """
    limite = time.monotonic() + max(espera, 0.0)
    while True:
        if await _suena(manager, Estado, titulo):
            return True
        ventana = _ventana_del_video(titulo)
        if ventana is not None and _traer_al_frente(ventana):
            break
        if time.monotonic() >= limite:
            return False
        await asyncio.sleep(INTERVALO_SONDEO)

    await _callar_lo_anterior(manager, Estado, titulo)

    _pulsar_play_pausa()

    # A partir de aquí ya funcionó: la pestaña era la correcta y la tecla se
    # envió. Lo que queda es mirar un momento si la sesión llega a tiempo para
    # contestar con el estado real, no un examen que el vídeo pueda suspender.
    limite = time.monotonic() + CONFIRMACION
    while time.monotonic() < limite:
        if await _suena(manager, Estado, titulo):
            break
        await asyncio.sleep(INTERVALO_SONDEO)
    return True


# El puerto de depuración del navegador de Vibi. Es el mismo que declara
# `navegador_real` al lanzarlo y el que usa el MCP de Playwright; aquí se
# consulta, no se abre.
PUERTO_NAVEGADOR = 9333

# Lo que se le pregunta a una pestaña para darle al play. Devuelve qué pasó en
# vez de un «ya está»: si la página no tiene vídeo, o el navegador rechaza la
# reproducción automática, hay que poder decirlo en vez de dar por hecho.
JS_PLAY = """(async () => {
    const medio = document.querySelector('video, audio');
    if (!medio) return JSON.stringify({estado: 'sin_video'});
    if (!medio.paused) return JSON.stringify({estado: 'ya_sonaba'});
    try {
        await medio.play();
    } catch (error) {
        return JSON.stringify({estado: 'rechazado', motivo: String(error)});
    }
    return JSON.stringify({estado: medio.paused ? 'sigue_pausado' : 'sonando'});
})()"""


async def _play_por_navegador(titulo: str) -> dict | None:
    """Le da al play a esa pestaña sin traerla al frente. `None` si no se pudo.

    Devolver `None` en vez de lanzar es lo que permite que esto sea un intento:
    si el navegador de Vibi no está abierto, o el vídeo no está en él, o la
    pestaña no responde, quien llama sigue con el camino de siempre. Aquí no se
    decide nada, se prueba lo barato antes de lo caro.
    """
    from . import cdp

    try:
        paginas = cdp.pestanas(PUERTO_NAVEGADOR)
        pagina = cdp.elegir(paginas, titulo)
        crudo = await cdp.evaluar(pagina, JS_PLAY)
    except Exception:
        return None

    try:
        import json as _json

        respuesta = _json.loads(str(crudo))
    except Exception:
        return None
    if respuesta.get("estado") not in ("sonando", "ya_sonaba"):
        return None

    return {
        "accion": "play",
        "obedecida": True,
        "titulo": pagina.get("title") or titulo,
        "app": "el navegador",
        "sonando": True,
        "via": "hablándole a la pestaña, sin ponerla delante",
    }


async def _control_windows(accion: str, titulo: str | None, espera: float) -> dict:
    Manager, Estado = _cargar_windows()
    manager = await Manager.request_async()

    sesion = await _elegir(manager, Estado, titulo)

    # Un vídeo recién abierto no está entre las sesiones y no va a estarlo por
    # esperar: mientras no suene, para Windows no existe.
    if sesion is None and accion == "play" and titulo:
        # Primero por el navegador, hablándole a la pestaña directamente. Es
        # la vía buena y la que arregla el fallo más repetido de esta
        # capacidad: **31 errores de 82 (38 %)**, todos «su pestaña no ha
        # llegado a estar delante», con mediana de 3,6 s y p90 de 11 s.
        # Traerte la pestaña al frente para pulsar una tecla era además lo
        # contrario de lo que se pide: darle al play sin que te tapen nada.
        por_el_navegador = await _play_por_navegador(titulo)
        if por_el_navegador is not None:
            return por_el_navegador
        # Y si no hay navegador enganchado —o el vídeo no está en él—, queda
        # lo de siempre: ponerlo delante y pulsar la tecla.
        if await _arrancar_pestana(manager, Estado, titulo, espera):
            # El estado se mide, no se supone: la sesión puede tardar más que
            # la confirmación en publicarse, y contestar «sonando» a ciegas
            # sería inventarse la única parte que se puede comprobar.
            sesion = await _elegir(manager, Estado, titulo)
            descripcion = (
                await _describir(sesion, Estado)
                if sesion is not None
                else Sonando(titulo, None, None, False)
            )
            return {"accion": accion, "obedecida": True, **descripcion.como_dict()}
        raise MediaError(
            f"«{titulo}» está abierto, pero no he llegado a darle al play: "
            "su pestaña no ha llegado a estar delante. Dale tú."
        )

    if sesion is None:
        raise MediaError(
            f"No encuentro «{titulo}» sonando en este dispositivo."
            if titulo
            else "No hay nada reproduciéndose ahora mismo en este dispositivo."
        )

    ordenes = {
        "play": sesion.try_play_async,
        "pause": sesion.try_pause_async,
        "next": sesion.try_skip_next_async,
        "previous": sesion.try_skip_previous_async,
    }
    obedecida = bool(await ordenes[accion]())
    descripcion = await _asentar(sesion, Estado, accion)
    return {"accion": accion, "obedecida": obedecida, **descripcion.como_dict()}


# Windows tarda un instante en reflejar el cambio: preguntar de inmediato
# devuelve el estado anterior.
ASENTAMIENTO = 1.5


async def _asentar(sesion, Estado, accion: str) -> Sonando:
    """Espera a que el cambio se note antes de contar qué ha pasado.

    Sin esto, un «pausa» contestaba `sonando: True` y Vibi se creía que no
    había funcionado. Se espera poco y con tope: más vale contestar el estado
    de hace un segundo que quedarse colgado esperando a que cambie.
    """
    esperado = {"play": True, "pause": False}.get(accion)
    limite = time.monotonic() + ASENTAMIENTO
    descripcion = await _describir(sesion, Estado)
    while esperado is not None and descripcion.sonando != esperado:
        if time.monotonic() >= limite:
            break
        await asyncio.sleep(0.2)
        descripcion = await _describir(sesion, Estado)
    if esperado is None:
        # Saltar de pista no cambia si suena, cambia el título: se espera a que
        # llegue uno distinto en vez de dormir un rato fijo, que era pagar el
        # mismo precio siempre incluso cuando ya había cambiado.
        antes = descripcion.titulo
        while descripcion.titulo == antes and time.monotonic() < limite:
            await asyncio.sleep(0.15)
            descripcion = await _describir(sesion, Estado)
    return descripcion


async def _now_playing_windows() -> dict:
    Manager, Estado = _cargar_windows()
    manager = await Manager.request_async()
    # Por la misma puerta que las órdenes, para que no conteste «suena Vibi»
    # cuando lo que quieres saber es qué música tienes puesta.
    sesion = await _elegir(manager, Estado, None)
    if sesion is None:
        return Sonando(None, None, None, False).como_dict()
    return (await _describir(sesion, Estado)).como_dict()


# ---------- Frontera por sistema ----------

def _sin_soporte() -> None:
    raise MediaError(
        f"Este dispositivo ({platform.system()}) todavía no sabe controlar la "
        "reproducción. De momento solo lo hace Windows."
    )


def control(accion: str, titulo: str | None = None, espera: float = 0.0) -> dict:
    """Manda una orden a lo que esté sonando. Síncrona: la llama un hilo."""
    if accion not in ACCIONES:
        raise MediaError(
            f"No sé hacer «{accion}». Puedo: {', '.join(ACCIONES)}."
        )
    if platform.system() != "Windows":
        _sin_soporte()
    return asyncio.run(_control_windows(accion, titulo, espera))


def now_playing() -> dict:
    """Qué se está reproduciendo, si es que hay algo."""
    if platform.system() != "Windows":
        _sin_soporte()
    return asyncio.run(_now_playing_windows())

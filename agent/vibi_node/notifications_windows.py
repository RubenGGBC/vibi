"""Lo que Windows te está notificando, leído desde aquí.

El companion ya sabía avisarte —`tauri_plugin_notification`— y esto es la mitad
que faltaba: enterarse de lo que te avisan los demás. Detrás está
`UserNotificationListener`, la misma API que usan los relojes y los auriculares
para repetirte los mensajes en la muñeca.

**Se sondea, no se escucha.** El listener tiene un evento
(`NotificationChanged`) y aquí no existe: suscribirse falla en el sitio con
`ERROR_NOT_FOUND`, porque Windows solo lo sirve a aplicaciones empaquetadas en
MSIX y el nodo es un proceso de Python suelto. Empaquetar el agente como
aplicación de la Store para ganar dos segundos no sale a cuenta.

**Y sondear sale gratis, aunque no lo parezca.** Cada lectura tarda 444 ms de
reloj —medido el 2026-08-16 en este equipo, y da igual esperarla con `.get()`
que con `await`: es lo que cuesta la API—. Ese número asusta hasta que se mide
la otra mitad: **0,0 ms de CPU**. Es una llamada que cruza a otro proceso y se
queda esperando, así que el hilo está parado, no trabajando. Sondear cada
segundo y medio consume un 0 % de núcleo; lo único que cuesta es que el aviso
llega hasta dos segundos tarde, y para «Ana te ha escrito» eso no se nota.

**Cada sondeo devuelve el centro entero, no lo nuevo.** Por eso existe `Vigia`:
sin memoria de lo ya visto, Vibi te leería los mismos ocho avisos cada segundo
y medio. Y por eso el primer sondeo no cuenta como novedad — al encender el
agente hay notificaciones que llevan ahí desde ayer y no son noticia.

Un dato de la primera lectura en este equipo, que explica por qué el filtro no
podía ser una lista blanca: de las ocho notificaciones acumuladas, cuatro eran
la misma promoción de NVIDIA repetida, dos de Xbox, una de OneDrive vendiendo su
IA y un resumen de Defender. Ninguna era una persona escribiendo.
"""
from __future__ import annotations

import platform
import threading
from dataclasses import dataclass

# Cuánto se espera entre sondeos, además de los 444 ms que tarda la lectura.
# Corto porque «Ana te ha escrito» dicho medio minuto tarde ya no sirve de nada,
# y se puede permitir porque la espera no consume CPU (ver arriba).
INTERVALO = 1.5

# Cuántos identificadores de notificación se recuerdan para no repetirse. Los
# ids de Windows crecen y no se reciclan, así que basta con recordar los
# últimos: un equipo encendido semanas no puede ir acumulándolos para siempre.
MAX_VISTAS = 2_000

# Cuánto se aguanta una lectura antes de darla por perdida. Tarda 444 ms; el
# tope está para el caso en que el servicio de notificaciones se atasque y no
# para acotar una lectura normal.
TIMEOUT_LECTURA = 15.0

APP_DESCONOCIDA = "desconocida"


class ErrorNotificaciones(Exception):
    pass


@dataclass(frozen=True)
class Aviso:
    """Una notificación, ya sin nada de WinRT dentro."""

    id: int
    app: str
    titulo: str
    cuerpo: str
    cuando: str

    def __str__(self) -> str:
        cabeza = f"[{self.app}] {self.titulo}".strip()
        return f"{cabeza}: {self.cuerpo}" if self.cuerpo else cabeza


# ---------- La API de Windows ----------

def _api():
    """Las tres piezas de WinRT que hacen falta, importadas al usarlas.

    Los dos primeros no se usan por nombre y hay que importarlos igual: son los
    que enseñan a la proyección de Python qué es un `AppInfo` y qué es un
    `XmlDocument`. Sin ellos, leer el nombre de la aplicación da AttributeError.
    """
    if platform.system() != "Windows":
        raise ErrorNotificaciones("Las notificaciones solo se leen en Windows")
    try:
        import winrt.windows.applicationmodel  # noqa: F401  - proyecta AppInfo
        import winrt.windows.data.xml.dom  # noqa: F401  - proyecta XmlDocument
        import winrt.windows.ui.notifications as notificaciones
        import winrt.windows.ui.notifications.management as gestion
    except ImportError as error:
        raise ErrorNotificaciones(
            "Me falta el paquete de notificaciones de Windows. Instálalo con "
            "«pip install -r agent/requirements.txt»."
        ) from error
    return gestion, notificaciones


def permiso_concedido() -> bool:
    """Si el usuario nos deja leer sus notificaciones.

    Se consulta y no se pide: pedirlo abre un diálogo del sistema, y eso no
    puede pasar porque alguien haya preguntado de pasada si la capacidad existe.
    Pedirlo es `pedir_permiso`, y lo llama el arranque del agente.
    """
    gestion, _ = _api()
    escucha = gestion.UserNotificationListener.current
    estado = escucha.get_access_status()
    return int(estado) == int(gestion.UserNotificationListenerAccessStatus.ALLOWED)


def _en_hilo_propio(trabajo):
    """Ejecuta `trabajo` en un hilo recién nacido y devuelve lo que saque.

    Dos reglas de COM se juntan aquí, y ninguna de las dos se ve venir:

    **No se puede bloquear desde un apartamento de un solo hilo.** Los
    `IAsyncOperation` de WinRT traen un `get()` que espera al resultado, y en un
    hilo STA revienta con «Cannot call blocking method from single-threaded
    apartment» — bloquear ahí es justo lo que produciría un interbloqueo.
    No es hipotético: `ui_windows._automation()` deja el hilo en STA al preparar
    UIA, las órdenes del nodo se atienden desde el hilo que toque, y mirar una
    ventana y leer las notificaciones acaban cayendo en el mismo.

    **Y un objeto de COM no cruza de hilo.** Por eso entra aquí el trabajo
    entero y no solo la espera: crear el listener fuera y usarlo dentro falla
    con «una interfaz que se aplanó para un diferente subproceso». Lo que
    devuelva `trabajo` tiene que ser Python de verdad —listas, cadenas—, no
    objetos de WinRT, o el fallo reaparece al leerles una propiedad fuera.

    Un hilo cuesta una décima de milisegundo contra los 444 ms de la llamada,
    así que no hay nada que ahorrar reutilizándolo.
    """
    resultado: dict[str, object] = {}

    def envoltorio():
        try:
            resultado["valor"] = trabajo()
        except BaseException as error:  # noqa: BLE001 - se recoge y se relanza
            resultado["error"] = error

    hilo = threading.Thread(target=envoltorio, daemon=True, name="vibi-notif")
    hilo.start()
    hilo.join(TIMEOUT_LECTURA)
    if hilo.is_alive():
        raise ErrorNotificaciones(
            f"Windows no contestó a la lectura de notificaciones en "
            f"{TIMEOUT_LECTURA}s"
        )
    if "error" in resultado:
        raise resultado["error"]  # type: ignore[misc]
    return resultado["valor"]


def pedir_permiso() -> bool:
    """Pide el permiso, abriendo el diálogo del sistema si hace falta."""
    gestion, _ = _api()
    permitido = int(gestion.UserNotificationListenerAccessStatus.ALLOWED)

    def trabajo() -> int:
        escucha = gestion.UserNotificationListener.current
        return int(escucha.request_access_async().get())

    return _en_hilo_propio(trabajo) == permitido


def disponible() -> bool:
    """Si esta máquina puede leer notificaciones ahora mismo."""
    try:
        return permiso_concedido()
    except Exception:
        return False


def _componer(id_: int, app: str, textos: list[str], cuando: str) -> Aviso:
    """De los textos sueltos que da Windows a algo con forma.

    Windows entrega los elementos de texto en orden y sin decir cuál es cuál.
    En la práctica el primero es siempre el título —quién escribe, o de qué va—
    y el resto el cuerpo, así que se parte ahí y los demás se juntan.
    """
    limpios = [" ".join(str(t).split()) for t in textos]
    limpios = [t for t in limpios if t]
    titulo = limpios[0] if limpios else ""
    cuerpo = " ".join(limpios[1:])
    return Aviso(
        id=int(id_),
        app=(app or "").strip() or APP_DESCONOCIDA,
        titulo=titulo,
        cuerpo=cuerpo,
        cuando=cuando,
    )


def _textos(notificacion) -> list[str]:
    salida: list[str] = []
    try:
        for binding in notificacion.visual.bindings:
            salida.extend(elemento.text for elemento in binding.get_text_elements())
    except Exception:
        # Una notificación sin plantilla de texto —solo imagen, o de un
        # programa que la construye a mano— no puede llevarse por delante al
        # resto de la lectura.
        return []
    return salida


def leer() -> list[Aviso]:
    """Todo lo que hay ahora mismo en el centro de notificaciones.

    La lectura entera ocurre dentro de `_en_hilo_propio`, y sale de ahí
    convertida a cadenas y números: los objetos de WinRT no pueden salir del
    hilo donde nacieron, así que leerles una propiedad fuera fallaría.
    """
    gestion, notificaciones = _api()

    def trabajo() -> list[tuple]:
        escucha = gestion.UserNotificationListener.current
        crudas = escucha.get_notifications_async(
            notificaciones.NotificationKinds.TOAST
        ).get()

        salida = []
        for cruda in crudas:
            try:
                app = cruda.app_info.display_info.display_name
            except Exception:
                app = ""
            try:
                cuando = cruda.creation_time.isoformat()
            except Exception:
                cuando = ""
            salida.append((int(cruda.id), str(app), _textos(cruda.notification), cuando))
        return salida

    return [_componer(*datos) for datos in _en_hilo_propio(trabajo)]


# ---------- Quedarse solo con lo nuevo ----------

class Vigia:
    """Recuerda qué notificaciones ya se contaron.

    El primer sondeo no devuelve nada a propósito: lo que hay en el centro al
    encender el agente lleva ahí desde antes y ya lo has visto.
    """

    def __init__(self) -> None:
        self._vistas: dict[int, None] = {}
        self._estrenado = False

    def novedades(self, avisos: list[Aviso]) -> list[Aviso]:
        nuevas = [a for a in avisos if a.id not in self._vistas]
        for aviso in avisos:
            # Reinsertar mueve la clave al final: así podar tira lo antiguo y
            # no lo que sigue en pantalla.
            self._vistas.pop(aviso.id, None)
            self._vistas[aviso.id] = None
        self._podar()
        if not self._estrenado:
            self._estrenado = True
            return []
        return nuevas

    def _podar(self) -> None:
        sobran = len(self._vistas) - MAX_VISTAS
        for _ in range(max(0, sobran)):
            self._vistas.pop(next(iter(self._vistas)))

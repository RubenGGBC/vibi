"""El árbol de accesibilidad de Windows, vía UI Automation.

Traduce lo que publica UIA a los `Nodo` de `ui_tree` y ejecuta acciones sobre
elementos concretos. Todo lo que no sea recorrer o actuar —podar, numerar,
buscar, dibujar— vive en `ui_tree` y es el mismo código que en macOS.

**Se recorre con `CacheRequest` y no leyendo propiedades sueltas.** No es una
optimización: es la diferencia entre que esto exista o no. UIA cobra un salto
entre procesos por cada propiedad de cada elemento, y medido en este equipo el
2026-08-13, el árbol de Zen Browser cuesta 3.076 ms leído a pelo y 119 ms con
una petición de caché. Con tres segundos por vistazo, mirar por accesibilidad
sería más lento que sacar una foto.

**El árbol de Chromium y Electron hay que despertarlo.** Estas apps no lo
construyen hasta que notan a un cliente asistivo preguntando, y no lo tienen
listo al instante: VS Code pasó de 14 nodos a 2.468, y Zen de 1.464 a 3.596
entre dos consultas separadas por un segundo. Por eso una primera respuesta
sospechosamente pequeña no se da por buena.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from . import computer, ui_tree
from .ui_tree import Nodo, Rect

# El CLSID de CUIAutomation. Va escrito porque `comtypes` solo genera los
# interfaces del type library, no las clases con las que se instancian.
CLSID_CUIAUTOMATION = "{FF48DBA4-60EF-4201-AA87-54103EEF594E}"

TREESCOPE_ELEMENTO = 1
TREESCOPE_HIJOS = 2

# Cuánto se le da al recorrido antes de devolver lo que lleve. Es la red para
# la ventana patológica; ninguna de las medidas en este equipo pasó de 250 ms.
PRESUPUESTO_ARBOL = 8.0

# Hasta dónde se baja. Una jerarquía cíclica o absurdamente profunda no puede
# dejar el recorrido dando vueltas.
MAX_PROFUNDIDAD = 60

# Las propiedades que se piden de una vez. Cada una que se añada aquí es
# gratis; cada una que falte y se lea después cuesta un salto entre procesos
# por elemento del árbol.
P_NOMBRE = 30005
P_TIPO = 30003
P_RECT = 30001
P_HABILITADO = 30010
P_FUERA_DE_PANTALLA = 30022
P_RUNTIME_ID = 30000
P_VALOR = 30045
P_TOGGLE = 30086
P_EXPANDIR = 30070
P_SELECCIONADO = 30079
P_FOCO = 30008
P_ES_INVOCABLE = 30031
P_ES_ESCRIBIBLE = 30043
P_ES_MARCABLE = 30041
P_ES_SELECCIONABLE = 30036
P_ES_EXPANDIBLE = 30029

PROPIEDADES = (
    P_NOMBRE, P_TIPO, P_RECT, P_HABILITADO, P_FUERA_DE_PANTALLA,
    P_RUNTIME_ID, P_VALOR, P_TOGGLE, P_EXPANDIR, P_SELECCIONADO, P_FOCO,
    P_ES_INVOCABLE, P_ES_ESCRIBIBLE, P_ES_MARCABLE, P_ES_SELECCIONABLE,
    P_ES_EXPANDIBLE,
)

PATRON_INVOCAR = 10000
PATRON_VALOR = 10002
PATRON_EXPANDIR = 10005
PATRON_SELECCIONAR = 10010
PATRON_MARCAR = 10015
PATRON_ANTIGUO = 10018
# `Text` es el respaldo para comprobar lo escrito: un editor rico dentro de
# Chromium no publica `Value` pero sí lo que se ve como texto.
PATRON_TEXTO = 10014

# Cuánto se lee de un cuadro de texto al comprobar. No es un límite de la app:
# es que comprobar «¿está mi frase ahí?» no necesita traerse un documento
# entero cruzando la frontera del proceso.
MAX_TEXTO_VERIFICACION = 4000

PATRON_DESPLAZAR = 10004
PATRON_DESPLAZAR_ITEM = 10017

# Los `ScrollAmount` de UIA. Se usa el salto grande —una página— y no el
# pequeño porque quien pide «baja» quiere avanzar por la lista, no una línea:
# con el pequeño harían falta veinte pasos para lo que se ve de un vistazo.
SIN_MOVER = 2
PAGINA_ATRAS = 0
PAGINA_ADELANTE = 3

# dirección -> (horizontal, vertical)
MOVIMIENTOS = {
    "abajo": (SIN_MOVER, PAGINA_ADELANTE),
    "arriba": (SIN_MOVER, PAGINA_ATRAS),
    "derecha": (PAGINA_ADELANTE, SIN_MOVER),
    "izquierda": (PAGINA_ATRAS, SIN_MOVER),
}

# Un tope para que «veces» no se convierta en un bucle largo dentro del lote.
MAX_DESPLAZAMIENTOS = 20

# Por debajo de esto, el árbol de una ventana no se cree del todo: una ventana
# con contenido tiene barra de título, botones y cuerpo. Pero «no me lo creo» no
# es lo mismo en todas: ver `clase_perezosa` y `_despertar`.
MINIMO_CREIBLE = 30

# Cuánto se espera a una ventana que **sí** puede estar construyendo su árbol, y
# cada cuánto se le vuelve a preguntar.
#
# Medido en este equipo el 2026-08-15, sondeando un VS Code recién abierto cada
# 50 ms: **ocho sondeos seguidos planos en 16 nodos —646 ms— y salto a 170 en
# t+844 ms**, asentándose en 251 a los 2,4 s. El despertar no es gradual: es una
# meseta y después un salto. Los 600 ms que había antes se agotaban justo antes
# de que el árbol existiera, así que la ventana se daba por muda precisamente en
# el caso para el que se escribió la espera.
PRESUPUESTO_DESPERTAR = 2.5
SONDEO_DESPERTAR = 0.05

# Lo que se le da a un campo para publicar el valor que se le acaba de poner,
# antes de darlo por no escrito. Una app web mete el texto en su DOM y el árbol
# de UIA se entera en la vuelta siguiente. Medido en Discord el 2026-08-20: la
# primera lectura contesta el valor viejo y la segunda ya dice la verdad.
ESPERA_VALOR = 0.08

# Las clases de ventana de Win32 que construyen su árbol solo cuando notan a un
# cliente asistivo preguntando. Todo lo demás publica lo que tiene desde el
# primer momento, y esperarle es tiempo tirado.
#
# Medido en este equipo: `Chrome_WidgetWin_1` son exactamente VS Code y Discord;
# Raycast es `HwndWrapper[…]`, Zen `MozillaWindowClass`, BakkesMod
# `Qt5QWindowIcon`, la terminal `CASCADIA_HOSTING_WINDOW_CLASS` y el companion su
# propia clase de Tauri. Gecko va en la lista aunque aquí no llegara a hacer
# falta —Zen publicaba 40 nodos de entrada— porque también construye su árbol
# bajo demanda, y equivocarse por ese lado es peor: de más se pierden segundos
# en una ventana pequeña, de menos se declara muda una que sí iba a hablar.
# `winuidesktop…` y `microsoft.ui.content…` son la envoltura de las apps de la
# Store hechas con WinUI 3, y muchas llevan un WebView2 dentro: WhatsApp
# Desktop sin ir más lejos, cuyo árbol dice `documento "WhatsApp" =
# "https://web.whatsapp.com/…"`. Por fuera parecen nativas y por dentro es
# Chromium con las mismas prisas, así que sin ellas en la lista una ventana
# fría se daba por muda sin haberle dado un momento. Encontrado el 2026-08-20.
CLASES_PEREZOSAS = (
    "chrome_widgetwin_",
    "mozillawindowclass",
    "winuidesktopwin32windowclass",
    "microsoft.ui.content.",
)


class ErrorUI(Exception):
    pass


# ---------- La instancia de UIA ----------

_local = threading.local()


def _automation():
    """La instancia de este hilo.

    Los objetos COM no se pasan entre hilos sin más, y el agente atiende
    órdenes desde donde le toque. Una por hilo es más barato que ponerse a
    hacer marshalling.
    """
    instancia = getattr(_local, "uia", None)
    if instancia is not None:
        return instancia

    try:
        import comtypes
        import comtypes.client
    except ImportError as error:  # pragma: no cover - depende de la máquina
        raise ErrorUI(
            "Falta comtypes en esta máquina. Instálalo con "
            "«pip install -r agent/requirements.txt»."
        ) from error

    try:
        comtypes.CoInitializeEx()
    except (OSError, ValueError):
        # Ya inicializado en este hilo, posiblemente con otro apartamento.
        # UIA funciona en los dos, así que no es motivo para parar.
        pass

    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as UIA

    _local.gen = UIA
    _local.uia = comtypes.client.CreateObject(
        CLSID_CUIAUTOMATION, interface=UIA.IUIAutomation
    )
    return _local.uia


def _gen():
    _automation()
    return _local.gen


def disponible() -> bool:
    """Si esta máquina sabe leer árboles de accesibilidad."""
    try:
        _automation()
        return True
    except Exception:
        return False


# ---------- Lectura de propiedades ----------

def _cacheado(elemento, propiedad, por_defecto=None):
    try:
        valor = elemento.GetCachedPropertyValue(propiedad)
    except Exception:
        return por_defecto
    return por_defecto if valor is None else valor


def _texto(elemento, propiedad) -> str:
    valor = _cacheado(elemento, propiedad, "")
    return valor if isinstance(valor, str) else ""


def _rect(elemento) -> Rect:
    """El rectángulo, que llega como cuatro dobles y no como un RECT.

    Cacheada, `BoundingRectangle` viene en la forma que usa UIA por dentro
    —izquierda, arriba, ancho, alto— y no en la del struct que devuelve
    `CurrentBoundingRectangle`. Confundirlas da rectángulos absurdos que la
    poda descarta enteros, así que el árbol sale vacío sin decir por qué.
    """
    crudo = _cacheado(elemento, P_RECT)
    try:
        valores = [float(v) for v in crudo]
    except (TypeError, ValueError):
        return ui_tree.RECT_NULO
    if len(valores) != 4:
        return ui_tree.RECT_NULO
    izquierda, arriba, ancho, alto = valores
    return Rect(
        int(izquierda), int(arriba), int(izquierda + ancho), int(arriba + alto)
    )


def _identidad(elemento) -> tuple:
    crudo = _cacheado(elemento, P_RUNTIME_ID)
    try:
        return tuple(int(v) for v in crudo)
    except (TypeError, ValueError):
        return ()


def _estado(elemento) -> frozenset[str]:
    """Los estados que el elemento realmente tiene.

    Cada uno se pregunta solo si su patrón existe, y no leyendo la propiedad a
    secas. `GetCachedPropertyValue` devuelve el **valor por defecto** de una
    propiedad que el elemento no soporta, y el de `ToggleState` es
    «indeterminado»: sin esta comprobación, un documento de texto y una
    pestaña salían como casillas a medio marcar.
    """
    estados = set()
    if _cacheado(elemento, P_HABILITADO, True) is False:
        estados.add("desactivado")
    if _cacheado(elemento, P_FUERA_DE_PANTALLA, False) is True:
        estados.add("oculto")
    if _cacheado(elemento, P_FOCO, False) is True:
        estados.add("con foco")

    if _cacheado(elemento, P_ES_MARCABLE, False) is True:
        marcado = _cacheado(elemento, P_TOGGLE)
        if marcado == 1:
            estados.add("marcado")
        elif marcado == 2:
            estados.add("a medias")

    if _cacheado(elemento, P_ES_EXPANDIBLE, False) is True:
        expandido = _cacheado(elemento, P_EXPANDIR)
        if expandido == 0:
            estados.add("contraído")
        elif expandido == 1:
            estados.add("expandido")

    if _cacheado(elemento, P_ES_SELECCIONABLE, False) is True:
        if _cacheado(elemento, P_SELECCIONADO, False) is True:
            estados.add("seleccionado")
    return frozenset(estados)


def _accionable(elemento) -> bool:
    """Si el sistema dice que se le puede hacer algo.

    Se pregunta por los patrones y no por el tipo de control: un `Text` puede
    ser invocable y un `Button` puede estar ahí de adorno, y quien lo sabe es
    la aplicación.
    """
    for propiedad in (
        P_ES_INVOCABLE, P_ES_ESCRIBIBLE, P_ES_MARCABLE,
        P_ES_SELECCIONABLE, P_ES_EXPANDIBLE,
    ):
        if _cacheado(elemento, propiedad, False) is True:
            return True
    return False


# ---------- Recorrido ----------

def _peticion_nivel():
    """El elemento y sus hijos directos, con todas las propiedades de golpe.

    Un solo nivel por llamada. Pedir el subárbol entero sería menos llamadas y
    no se hace: ver `_traer_arbol`.
    """
    uia = _automation()
    peticion = uia.CreateCacheRequest()
    peticion.TreeScope = TREESCOPE_ELEMENTO | TREESCOPE_HIJOS
    for propiedad in PROPIEDADES:
        peticion.AddProperty(propiedad)
    # La vista de control ya se deja fuera buena parte de los envoltorios
    # anónimos, antes incluso de que los pode `ui_tree`.
    peticion.TreeFilter = uia.ControlViewCondition
    return peticion


def _uno(elemento, hijos: tuple) -> Nodo:
    """Un elemento ya cacheado, convertido a `Nodo`."""
    # Solo tiene valor lo que lo publica: si no, `GetCachedPropertyValue`
    # devolvería el valor por defecto de la propiedad y no el del elemento.
    valor = None
    if _cacheado(elemento, P_ES_ESCRIBIBLE, False) is True:
        valor = ui_tree.recortar_valor(_texto(elemento, P_VALOR))
    return Nodo(
        rol=ui_tree.rol_uia(_cacheado(elemento, P_TIPO, 0)),
        nombre=_texto(elemento, P_NOMBRE),
        valor=valor,
        estado=_estado(elemento),
        rect=_rect(elemento),
        accionable=_accionable(elemento),
        hijos=hijos,
        nativo=elemento,
        identidad=_identidad(elemento),
    )


def _merece_bajar(elemento, ventana: Rect) -> bool:
    """Si vale la pena descender por este elemento.

    Cortar aquí es lo que hace barato el recorrido: lo que no se ve es la
    mayor parte del árbol de una aplicación moderna, y bajar por ello cuesta
    una llamada por nodo para tirarlo después.

    **Un rectángulo vacío no corta el descenso.** Hay contenedores sin
    geometría propia cuyo contenido sí se ve, y cortarlos se llevaba ventanas
    enteras. Solo se corta con lo que el sistema declara fuera de pantalla
    —que sí hereda a los hijos— y con lo que tiene tamaño y cae fuera.
    """
    if _cacheado(elemento, P_FUERA_DE_PANTALLA, False) is True:
        return False
    rect = _rect(elemento)
    if rect.vacio or ventana.vacio:
        return True
    return rect.solapa(ventana)


def _traer_arbol(elemento, ventana: Rect) -> Nodo:
    """Recorre la ventana nivel a nivel, cacheando cada nivel de una vez.

    **No se pide el subárbol entero en una llamada, aunque se pueda.** Esa era
    la primera versión y es más rápida cuando funciona, pero no siempre
    funciona: el árbol de WhatsApp la tumba con E_FAIL tras 5,7 s, medido y
    reproducible, y bajar por niveles lo lee en 149 ms. Peor todavía, hay
    ventanas donde no falla sino que devuelve un árbol incompleto sin decir
    nada, que es indistinguible de una aplicación sin accesibilidad.

    Un nivel por llamada sigue siendo barato —una petición trae todos los
    hijos con sus propiedades— y ninguna ventana de este equipo pasó de 250 ms.
    """
    fin = time.monotonic() + PRESUPUESTO_ARBOL

    def bajar(actual, profundidad: int) -> Nodo:
        if profundidad >= MAX_PROFUNDIDAD or time.monotonic() > fin:
            return _uno(actual, ())
        try:
            fresco = actual.BuildUpdatedCache(_peticion_nivel())
            coleccion = fresco.GetCachedChildren()
        except Exception:
            # Una rama que no contesta no se lleva por delante a la ventana.
            return _uno(actual, ())

        hijos = []
        # Las identidades de los hermanos ya recorridos en este nivel. UIA
        # devuelve a veces el mismo hijo dos veces —WhatsApp Desktop repite su
        # panel entero, 71 nodos— y bajar por él otra vez es pagar el doble
        # por un árbol que además sale ambiguo. Aquí se corta antes de gastar
        # una sola llamada COM; `ui_tree.podar` lo vuelve a mirar por si el
        # backend fuera otro.
        vistas: set[tuple] = set()
        if coleccion:
            for indice in range(coleccion.Length):
                try:
                    hijo = coleccion.GetElement(indice)
                    if not _merece_bajar(hijo, ventana):
                        continue
                    identidad = _identidad(hijo)
                    if identidad:
                        if identidad in vistas:
                            continue
                        vistas.add(identidad)
                    hijos.append(bajar(hijo, profundidad + 1))
                except Exception:
                    # Un elemento que muere a mitad no afecta a sus hermanos.
                    continue
        return _uno(fresco, tuple(hijos))

    raiz = elemento.BuildUpdatedCache(_peticion_nivel())
    return bajar(raiz, 0)


def clase_perezosa(clase: str) -> bool:
    """Si esa clase de ventana construye su árbol solo cuando le preguntan."""
    plana = (clase or "").casefold()
    return any(plana.startswith(marca) for marca in CLASES_PEREZOSAS)


def merece_esperar(clase_perezosa: bool, minimizada: bool) -> bool:
    """Si tiene sentido darle tiempo a esta ventana a publicar su árbol.

    **Una ventana minimizada no está durmiendo: está enrollada.** Su contenido
    no existe mientras siga así, y esperarle los 2,5 s del presupuesto es tirar
    ese tiempo en cada vistazo. Medido con Discord minimizado el 2026-08-20:
    2.604 ms para volver con los mismos 8 nodos que ya tenía a los 26.

    La salida no es restaurarla por nuestra cuenta —eso le tapa la pantalla a
    quien esté delante—, sino decirlo y dejar que se pida con `activar`.
    """
    return clase_perezosa and not minimizada


# Las ventanas perezosas a las que ya se esperó el presupuesto entero y aun así
# no dijeron nada, con cuándo se comprobó.
#
# Hace falta porque «puede dormir» y «está dormida» no son lo mismo. Discord es
# `Chrome_WidgetWin_1` y visible, y publica 8 nodos: trae la accesibilidad
# apagada, no dormida. Sin esta memoria pagaría los 2,5 s en **cada** vistazo,
# que es peor que lo que había antes. Con ella lo paga una vez por minuto: la
# primera vez no hay forma de saberlo sin esperar, las siguientes sí.
MEMORIA_MUDAS = 60.0
_mudas: dict[int, float] = {}


def _se_quedo_muda(handle: int) -> bool:
    """Si a esta ventana ya se le esperó en vano hace poco."""
    visto = _mudas.get(handle)
    return visto is not None and (time.monotonic() - visto) < MEMORIA_MUDAS


def _recordar_mudez(handle: int, muda: bool) -> None:
    if muda:
        _mudas[handle] = time.monotonic()
    else:
        # Despertó: se olvida, porque la próxima vez ya estará despierta y no
        # queremos que una mudez vieja le quite el presupuesto si se reinicia.
        _mudas.pop(handle, None)


def olvidar_mudas() -> None:
    """Tira la memoria de ventanas mudas. La usan las pruebas."""
    _mudas.clear()


def _despertar(elemento, ventana: Rect, puede_dormir: bool) -> Nodo:
    """Pide el árbol, y solo a quien puede estar dormido le da tiempo.

    Antes se esperaba igual a todas: dos reintentos con 300 ms entre medias
    para cualquier ventana que devolviera menos de `MINIMO_CREIBLE` nodos. Eso
    trataba como el mismo problema dos que no se parecen, y salía mal por los
    dos lados. Medido en este equipo el 2026-08-15:

    - **A la ventana pequeña de verdad le cobraba 600 ms de sueño puro.**
      Discord con 8 nodos tardaba 660 ms y el companion con 1 nodo, 623 —
      mientras VS Code, con 314, se leía en 143. Las pequeñas tardaban diez
      veces más que las grandes, y el recorrido en sí cuesta de 5 a 20 ms:
      todo lo demás era `time.sleep`.
    - **Y a la que sí dormía le faltaba tiempo.** El árbol de un VS Code recién
      abierto aparece a los 844 ms; con 600 ms de presupuesto se devolvían sus
      16 nodos de arranque y se daba la ventana por muda.

    Lo que separa los dos casos es la clase de la ventana, no el conteo. Se
    probó a cortar cuando el número dejara de crecer y **no vale**: durante los
    646 ms de meseta no crece y la ventana sí está dormida.
    """
    arbol = _traer_arbol(elemento, ventana)
    if not puede_dormir or ui_tree.contar(arbol) >= MINIMO_CREIBLE:
        return arbol

    fin = time.monotonic() + PRESUPUESTO_DESPERTAR
    while time.monotonic() < fin:
        time.sleep(SONDEO_DESPERTAR)
        arbol = _traer_arbol(elemento, ventana)
        if ui_tree.contar(arbol) >= MINIMO_CREIBLE:
            break
    return arbol


# ---------- Ventanas ----------

# Las ventanas del propio escritorio, que salen siempre y no son de nadie.
CLASES_DE_SISTEMA = frozenset({
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow", "Windows.UI.Core.CoreWindow",
})


@dataclass(frozen=True)
class Ventana:
    handle: int
    titulo: str
    rect: Rect
    minimizada: bool
    # La clase de Win32. Ya se leía para descartar las del escritorio; se
    # guarda además porque es lo que dice si esta ventana puede estar
    # construyendo su árbol todavía. Ver `clase_perezosa`.
    clase: str = ""


def ventanas() -> list[Ventana]:
    """Las ventanas visibles con título, preguntándole a user32 y no a UIA.

    Enumerarlas con el `TreeWalker` de UIA costaba 3,5 segundos en este
    equipo: cada salto a la ventana siguiente entra en el proceso que la
    dibuja, y basta con que uno vaya cargado —Opera tardaba 1,7 s— para que
    mirar la pantalla deje de ser instantáneo. `EnumWindows` no sale del
    proceso y tarda microsegundos.

    De paso trae dos cosas que UIA no da fácil: si la ventana está minimizada
    y su rectángulo de verdad.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    salida: list[Ventana] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visitar(handle, _):
        if not user32.IsWindowVisible(handle):
            return True
        largo = user32.GetWindowTextLengthW(handle)
        if largo <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(largo + 1)
        user32.GetWindowTextW(handle, buffer, largo + 1)
        titulo = buffer.value.strip()
        if not titulo:
            return True

        clase = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, clase, 256)
        if clase.value in CLASES_DE_SISTEMA:
            return True

        caja = wintypes.RECT()
        user32.GetWindowRect(handle, ctypes.byref(caja))
        salida.append(
            Ventana(
                handle=int(handle),
                titulo=titulo,
                rect=Rect(caja.left, caja.top, caja.right, caja.bottom),
                minimizada=bool(user32.IsIconic(handle)),
                clase=clase.value,
            )
        )
        return True

    user32.EnumWindows(visitar, 0)
    return salida


def handle_en_primer_plano() -> int:
    import ctypes

    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


# `ShowWindow`: restaurar una ventana minimizada sin cambiarle el tamaño que
# tenía. `SetForegroundWindow` sobre una minimizada la trae al frente pero la
# deja enrollada, y entonces el árbol vuelve vacío.
SW_RESTORE = 9


def activar(handle: int) -> bool:
    """Trae esa ventana al frente, y dice si de verdad se ha quedado ahí.

    **La respuesta importa más que la acción.** Windows le niega el primer
    plano a un proceso de fondo cuando otro lo retiene —un juego a pantalla
    completa, un diálogo modal, una app que acaba de arrancar—, y `SetForeground`
    devuelve cero sin más. Dar por hecho el cambio es exactamente el error que
    convierte un teclado en una pulsación sobre la ventana de otro.

    Confirma releyendo `GetForegroundWindow` en vez de fiarse del código de
    retorno, que en algunas versiones miente cuando la ventana ya estaba
    delante. Es la misma técnica que `media._traer_al_frente`, con la restauración
    añadida.
    """
    import ctypes
    import time

    if not handle:
        return False
    try:
        user32 = ctypes.windll.user32
        if int(user32.GetForegroundWindow()) == int(handle):
            return True
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, SW_RESTORE)
        user32.SetForegroundWindow(handle)
        # Windows anima el cambio de ventana; preguntar a bocajarro contesta
        # que no ha pasado nada. Medido: 100 ms sobra en este equipo.
        time.sleep(0.1)
        return int(user32.GetForegroundWindow()) == int(handle)
    except Exception:
        return False


def _elemento(ventana: Ventana):
    """El elemento de UIA de una ventana, por su handle."""
    try:
        return _automation().ElementFromHandle(ventana.handle)
    except Exception as error:
        raise ErrorUI(
            f'No se pudo abrir «{ventana.titulo}»: {type(error).__name__}'
        ) from error


def elegir_ventana(
    titulo: str | None = None, handle: int = 0
) -> tuple[Ventana, list[Ventana]]:
    """Qué ventana se mira, y cuáles son las demás.

    Con `handle` se va directo a esa ventana y **el título ni se consulta**.
    Es lo que permite que un lote sobreviva a una ventana que se retitula sola
    a mitad de la secuencia.
    """
    abiertas = ventanas()
    if not abiertas:
        raise ErrorUI("No hay ninguna ventana abierta con título")

    if handle:
        for ventana in abiertas:
            if ventana.handle == handle:
                return ventana, abiertas
        raise ErrorUI(
            "La ventana con la que estabas trabajando ya no existe: se ha "
            "cerrado mientras hacías esto. Vuelve a mirar qué hay abierto."
        )

    if titulo and titulo.strip():
        buscado = ui_tree.normalizar(titulo)
        exactas = [v for v in abiertas if ui_tree.normalizar(v.titulo) == buscado]
        parciales = [
            v for v in abiertas if buscado in ui_tree.normalizar(v.titulo)
        ]
        elegidas = exactas or parciales
        if not elegidas:
            nombres = ", ".join(f'"{v.titulo}"' for v in abiertas[:12])
            raise ErrorUI(
                f"No hay ninguna ventana que se llame «{titulo}». "
                f"Abiertas: {nombres}"
            )
        return elegidas[0], abiertas

    delante = handle_en_primer_plano()
    for ventana in abiertas:
        if ventana.handle == delante:
            return ventana, abiertas
    return abiertas[0], abiertas


def capturar(
    titulo: str | None = None, handle: int = 0
) -> tuple[Nodo, Rect, str, tuple[str, ...], str | None, int]:
    """El árbol crudo de una ventana, con su rectángulo y sus vecinas.

    Devuelve `(raiz, rect, titulo, otras, aviso, handle)`. La poda, el colapso
    y los refs los pone `ui.py`: aquí solo se lee. Con `handle` se lee esa
    ventana concreta y el título se ignora.
    """
    objetivo, abiertas = elegir_ventana(titulo, handle)

    aviso = None
    if objetivo.minimizada:
        # Y decirlo con la salida delante importa: minimizada no publica su
        # contenido por mucho que se insista, así que sin esta frase el modelo
        # se queda mirando un árbol de ocho nodos sin saber que hay una puerta.
        aviso = (
            f"Aviso: «{objetivo.titulo}» está minimizada, así que de ella solo "
            "se ve el marco: lo que hay dentro no existe mientras siga así, y "
            "volver a mirarla no va a cambiar nada. Si necesitas su contenido, "
            "restáurala con un paso `activar` en un lote — le taparás la "
            "pantalla, así que hazlo solo si hace falta y dilo."
        )
    elif objetivo.handle != handle_en_primer_plano():
        # Una ventana de fondo puede traer parte de su contenido marcado como
        # fuera de pantalla y quedarse corta al podar. Decirlo evita mandar a
        # depurar al sitio equivocado.
        aviso = (
            f"Aviso: «{objetivo.titulo}» no está en primer plano, así que "
            "puede aparecer incompleta. Ponla delante para verla entera."
        )

    elemento = _elemento(objetivo)
    perezosa = merece_esperar(
        clase_perezosa(objetivo.clase), objetivo.minimizada
    )
    try:
        arbol = _despertar(
            elemento, objetivo.rect, perezosa and not _se_quedo_muda(objetivo.handle)
        )
    except Exception as error:
        # Le pasó a Opera y a WhatsApp al medir: ventanas que mueren entre
        # listarlas y consultarlas, o procesos a los que no se llega. Es un
        # árbol no disponible, no un fallo del agente.
        raise ErrorUI(
            f"No se pudo leer el árbol de «{objetivo.titulo}»: "
            f"{type(error).__name__}. Míralo con una captura."
        ) from error

    if perezosa:
        # Y como `perezosa` ya excluye las minimizadas, una ventana enrollada
        # **no** se apunta como muda. Importa: si se apuntara, al restaurarla
        # se le negaría el presupuesto durante el minuto siguiente, que es
        # justo cuando lo necesita para construir su árbol desde cero.
        _recordar_mudez(
            objetivo.handle, ui_tree.contar(arbol) < MINIMO_CREIBLE
        )

    otras = tuple(
        v.titulo for v in abiertas if v.handle != objetivo.handle
    )[:8]
    # El rectángulo lo da user32 y no el árbol: una ventana minimizada publica
    # un elemento raíz sin geometría, y con él la poda se lo llevaría todo.
    # El handle va al final porque llegó después: es lo que permite preguntar
    # más tarde si esta ventana sigue teniendo el foco sin fiarse del título.
    return arbol, objetivo.rect, objetivo.titulo, otras, aviso, objetivo.handle


# ---------- Revalidación ----------

def sigue_vivo(nativo, huella: ui_tree.Huella) -> bool:
    """Si el `ref` sigue señalando lo mismo que cuando se numeró.

    Se comprueban las tres cosas porque cada una falla por su lado: el
    elemento puede haber muerto, puede seguir vivo con otro contenido —los
    controles se reciclan cuando una lista se repinta— o puede haber cambiado
    de nombre bajo los pies.
    """
    if nativo is None:
        return False
    try:
        peticion = _automation().CreateCacheRequest()
        for propiedad in (P_NOMBRE, P_TIPO, P_RUNTIME_ID):
            peticion.AddProperty(propiedad)
        fresco = nativo.BuildUpdatedCache(peticion)
    except Exception:
        return False
    if _identidad(fresco) != huella.identidad:
        return False
    if ui_tree.rol_uia(_cacheado(fresco, P_TIPO, 0)) != huella.rol:
        return False
    return _texto(fresco, P_NOMBRE) == huella.nombre


# ---------- Acciones ----------

def _patron(elemento, identificador, interfaz):
    try:
        crudo = elemento.GetCurrentPattern(identificador)
    except Exception:
        return None
    if not crudo:
        return None
    try:
        return crudo.QueryInterface(interfaz)
    except Exception:
        return None


def _centro(elemento) -> tuple[int, int] | None:
    try:
        rect = elemento.CurrentBoundingRectangle
    except Exception:
        return None
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2


def tiene_foco(elemento) -> bool:
    """Si ese elemento ya es donde va a caer lo que se teclee.

    Se lee en vivo y no del caché: entre leer el árbol y actuar puede haber
    pasado cualquier cosa, y esta pregunta solo vale respondida ahora.
    """
    try:
        return elemento.GetCurrentPropertyValue(P_FOCO) is True
    except Exception:
        return False


def _por_la_antigua(elemento, texto: str) -> bool:
    """Pone el texto por `LegacyIAccessible`, la interfaz de accesibilidad vieja.

    Es el puente con MSAA, y lo implementan montones de controles que no
    publican `Value` o que lo publican y no lo usan. Igual que con
    `DoDefaultAction` en `clic`, no es un adorno: es una puerta distinta a la
    misma habitación, y **no necesita el foco**, así que sirve justo cuando el
    foco es el problema.
    """
    UIA = _gen()
    antigua = _patron(
        elemento, PATRON_ANTIGUO, UIA.IUIAutomationLegacyIAccessiblePattern
    )
    if antigua is None:
        return False
    try:
        antigua.SetValue(texto)
    except Exception:
        return False
    quedo = valor_de(elemento)
    if quedo is None:
        # No publica su valor: se ha hecho lo que se podía y no hay forma de
        # comprobarlo desde aquí. Lo comprueba `ui._verificar_escritura` sobre
        # el árbol de después, que es quien tiene la última palabra.
        return True
    return ui_tree.texto_cuadra(quedo, texto)


def enfocar(elemento) -> None:
    try:
        elemento.SetFocus()
    except Exception as error:
        raise ErrorUI(f"No se pudo enfocar: {error}") from error


def clic(
    elemento, boton: str = "left", veces: int = 1, entrada_global: bool = True
) -> str:
    """Pulsa, agotando los patrones del sistema antes de tocar el ratón.

    Invocar por patrón no depende de dónde esté la ventana, de que algo la
    tape ni de que el puntero llegue: es la aplicación ejecutando su propia
    acción. El ratón queda para lo que no expone ninguno y para el clic
    derecho, que no tiene equivalente en UIA.

    **`entrada_global` es el permiso para bajar al ratón, y llega en `False`
    cuando la ventana no está delante.** El ratón pincha en coordenadas de
    pantalla, así que sobre una ventana tapada acierta el píxel y falla la
    ventana: pincha en lo que haya encima. Es lo que pasó el 19/08/2026 con
    WhatsApp detrás de un navegador. Sin permiso se dice que no se ha podido,
    que es la única respuesta honesta.

    **`DoDefaultAction` de LegacyIAccessible es el último patrón y no un
    adorno.** Es el puente con MSAA, la interfaz vieja, y lo implementan
    montones de controles que no publican `Invoke`: las celdas de una lista,
    lo que dibuja un framework antiguo, casi todo lo que se pinta a mano.
    Sin él, esos elementos caían al ratón, y el ratón puede no estar
    disponible.
    """
    UIA = _gen()
    if boton == "left" and veces == 1:
        invocar = _patron(elemento, PATRON_INVOCAR, UIA.IUIAutomationInvokePattern)
        if invocar is not None:
            invocar.Invoke()
            return "patrón invocar"

        seleccionar = _patron(
            elemento, PATRON_SELECCIONAR, UIA.IUIAutomationSelectionItemPattern
        )
        if seleccionar is not None:
            seleccionar.Select()
            return "patrón seleccionar"

        marcar = _patron(elemento, PATRON_MARCAR, UIA.IUIAutomationTogglePattern)
        if marcar is not None:
            marcar.Toggle()
            return "patrón marcar"

        expandir_patron = _patron(
            elemento, PATRON_EXPANDIR, UIA.IUIAutomationExpandCollapsePattern
        )
        if expandir_patron is not None:
            try:
                # Pulsar un desplegable es abrirlo si está cerrado y cerrarlo
                # si está abierto, que es lo que hace un clic de verdad.
                estado = expandir_patron.CurrentExpandCollapseState
                if estado == 1:
                    expandir_patron.Collapse()
                else:
                    expandir_patron.Expand()
                return "patrón expandir"
            except Exception:
                pass

        antiguo = _patron(
            elemento, PATRON_ANTIGUO, UIA.IUIAutomationLegacyIAccessiblePattern
        )
        if antiguo is not None:
            try:
                antiguo.DoDefaultAction()
                return "acción por defecto"
            except Exception:
                pass

    if not entrada_global:
        raise ErrorUI(
            f"«{_nombre_para_error(elemento)}» no admite pulsarse por patrón y "
            "su ventana no está delante: un clic por coordenadas caería en la "
            "ventana que la tape. Trae la ventana al frente primero, o busca "
            "un elemento equivalente que sí publique acción."
        )

    punto = _centro(elemento)
    if punto is None:
        raise ErrorUI(
            "Este elemento no admite ninguna acción y no tiene sitio en "
            "pantalla donde pinchar"
        )
    try:
        elemento.SetFocus()
    except Exception:
        pass
    computer.clic_escritorio(punto[0], punto[1], boton=boton, veces=veces)
    return "ratón"


def _nombre_para_error(elemento) -> str:
    """Cómo llamar a un elemento en un mensaje de error, sin reventar.

    Lee `CurrentName` en vivo y no `_texto`, que va contra el caché de una
    lectura previa: aquí el elemento puede venir de cualquier sitio.
    """
    try:
        nombre = elemento.CurrentName
    except Exception:
        return "ese elemento"
    return (nombre if isinstance(nombre, str) else "").strip() or "ese elemento"


def _valor_actual(valor) -> str | None:
    """Lo que el campo dice tener ahora, o None si no lo publica."""
    try:
        leido = valor.CurrentValue
    except Exception:
        return None
    return leido if isinstance(leido, str) else None


def valor_de(elemento) -> str | None:
    """El texto que tiene ese elemento, leído en vivo. None si no lo publica.

    Es lo que usa `ui._verificar_escritura` sobre el árbol releído, y por eso
    va contra el elemento fresco y no contra un caché: la gracia es preguntarle
    a la ventana cómo quedó, no repetir lo que creíamos.
    """
    if elemento is None:
        return None
    UIA = _gen()
    valor = _patron(elemento, PATRON_VALOR, UIA.IUIAutomationValuePattern)
    if valor is not None:
        return _valor_actual(valor)
    # Un cuadro de texto rico no publica `Value` pero sí `Text`, y ahí está lo
    # que se ve escrito. Es el caso de bastantes editores dentro de Chromium.
    texto = _patron(elemento, PATRON_TEXTO, UIA.IUIAutomationTextPattern)
    if texto is None:
        return None
    try:
        return texto.DocumentRange.GetText(MAX_TEXTO_VERIFICACION)
    except Exception:
        return None


def nombre_de(elemento) -> str:
    """Cómo se llama ese elemento ahora mismo."""
    return _nombre_para_error(elemento) if elemento is not None else ""


def escribir(elemento, texto: str, entrada_global: bool = True) -> str:
    """Pone texto en un campo, por patrón si se puede y tecleando si no.

    **Y comprueba que se haya puesto**, que es lo que faltaba. `SetValue` sobre
    algo que no es un campo editable —una celda de una lista, un contenedor de
    Chromium— no lanza ninguna excepción: se traga la llamada y devuelve. Con
    eso, el 19/08/2026 se dio por escrito un mensaje de WhatsApp que nunca se
    escribió, el modelo lo dio por enviado y se lo dijo a Rubén. Un `ok` que no
    significa nada es peor que un error.

    El orden es: patrón, comprobar, y solo si no ha entrado nada, teclado. Y el
    teclado necesita el foco, así que sin `entrada_global` se dice que no se ha
    podido en vez de teclear sobre la ventana de otro.
    """
    UIA = _gen()
    valor = _patron(elemento, PATRON_VALOR, UIA.IUIAutomationValuePattern)
    if valor is not None:
        try:
            if valor.CurrentIsReadOnly:
                raise ErrorUI("Ese campo es de solo lectura")
        except AttributeError:
            pass
        try:
            valor.SetValue(texto)
        except Exception as error:
            raise ErrorUI(
                f"No se pudo escribir en «{_nombre_para_error(elemento)}»: "
                f"{type(error).__name__}"
            ) from error

        # Una app web no cambia su valor en el mismo instante: el `SetValue`
        # entra en el DOM y el árbol de UIA se entera un poco después. Medido
        # en Discord el 20/08/2026: a bocajarro contesta el valor viejo, y con
        # una segunda lectura ya dice la verdad. Dos vistazos bastan; más sería
        # convertir una comprobación en una espera.
        quedo = _valor_actual(valor)
        if quedo is not None and not ui_tree.texto_cuadra(quedo, texto):
            time.sleep(ESPERA_VALOR)
            quedo = _valor_actual(valor)
        if quedo is not None and ui_tree.texto_cuadra(quedo, texto):
            return "patrón valor"
        if quedo is None:
            # No publica su valor, así que no hay forma de comprobarlo por
            # aquí. No es un fallo, pero tampoco es una confirmación: se dice
            # tal cual para que nadie lo lea como «hecho y verificado».
            return "patrón valor (sin poder comprobarlo)"
        # Ha aceptado la llamada y el campo sigue como estaba: es el ok falso.
        # Quedan la interfaz vieja y el teclado.
        if _por_la_antigua(elemento, texto):
            return "interfaz antigua"
        if not entrada_global:
            raise ErrorUI(
                f"«{_nombre_para_error(elemento)}» aceptó el texto pero se "
                f"quedó en «{quedo[:60]}»: no es un campo editable de verdad. "
                "Y su ventana no está delante, así que tampoco se puede "
                "teclear. Trae la ventana al frente, o busca el campo de "
                "escritura de verdad en el árbol."
            )
    else:
        # Sin `Value` queda la interfaz vieja, que la implementan controles que
        # no publican nada moderno. Se prueba antes de pedir el foco porque no
        # lo necesita.
        if _por_la_antigua(elemento, texto):
            return "interfaz antigua"
        if not entrada_global:
            raise ErrorUI(
                f"«{_nombre_para_error(elemento)}» no admite que le pongan "
                "texto por patrón y hay que teclearlo, pero su ventana no está "
                "delante: lo escrito acabaría en otra. Trae la ventana al "
                "frente primero."
            )

    # Y por último el teclado, que necesita el foco dentro del campo.
    #
    # **Si el campo ya tiene el foco, no se le pide.** Parece una obviedad y
    # costó un turno entero: el 20/08/2026 Vibi llegó al campo correcto de
    # WhatsApp —el árbol lo describía como «(con foco)»— y `SetFocus()` reventó
    # con «Un evento no pudo invocar a ninguno de los subscriptores», un
    # COMError de WebView2. Pedirle el foco a algo que ya lo tiene no puede ser
    # lo que impida escribir. Sin esto, el modelo se quedó dando clics tres
    # minutos y acabó abriendo aplicaciones que nadie había pedido.
    if not tiene_foco(elemento):
        try:
            enfocar(elemento)
        except ErrorUI:
            # El foco se negó y el campo tampoco lo tenía: teclear ahora sería
            # escribir a saber dónde. Se dice, con la salida delante, que es lo
            # que evita que quien lo reciba se ponga a probar cosas.
            raise ErrorUI(
                f"«{_nombre_para_error(elemento)}» no deja escribir de ninguna "
                "forma: no acepta que le pongan el texto y tampoco acepta el "
                "foco. Le pasa a las aplicaciones que por dentro son una "
                "página web metida en una ventana —WhatsApp entre ellas—. "
                "**Si esa aplicación tiene versión web, ábrela en el navegador "
                "y trabaja ahí**: la sesión ya está iniciada y sí se deja. No "
                "insistas por aquí a base de clics."
            ) from None
    computer.teclear(texto)
    return "teclado"


def desplazar(elemento, direccion: str = "abajo", veces: int = 1) -> str:
    """Mueve una lista o un panel, por patrón y sin tocar el foco.

    `ScrollPattern` es la aplicación desplazándose a sí misma: no depende de
    dónde esté el puntero, de que la ventana esté delante ni de que el elemento
    se vea. Es la diferencia con `devices_scroll`, que manda una rueda de ratón
    a unas coordenadas de pantalla y por tanto a lo que haya encima.

    Si el elemento no se desplaza pero **está dentro** de algo que sí —una
    fila de una tabla larga—, se usa `ScrollItem` para traerlo a la vista. Es
    lo que quiere quien dice «baja hasta ese mensaje».
    """
    UIA = _gen()
    desplazable = _patron(
        elemento, PATRON_DESPLAZAR, UIA.IUIAutomationScrollPattern
    )
    if desplazable is not None:
        horizontal, vertical = MOVIMIENTOS[direccion]
        movidos = 0
        for _ in range(max(1, min(veces, MAX_DESPLAZAMIENTOS))):
            try:
                desplazable.Scroll(horizontal, vertical)
            except Exception:
                # Llegar al final no es un fallo: `Scroll` lanza cuando ya no
                # se puede mover más en esa dirección. Si algo se movió, la
                # orden se cumplió hasta donde daba.
                break
            movidos += 1
        if movidos:
            return f"patrón desplazar ({movidos} de {veces})"
        raise ErrorUI(
            f"«{_nombre_para_error(elemento)}» ya está al final hacia "
            f"{direccion}: no se puede mover más por ahí."
        )

    traer = _patron(
        elemento, PATRON_DESPLAZAR_ITEM, UIA.IUIAutomationScrollItemPattern
    )
    if traer is not None:
        traer.ScrollIntoView()
        return "patrón traer a la vista"

    raise ErrorUI(
        f"«{_nombre_para_error(elemento)}» no se desplaza. Busca el contenedor "
        "que lo envuelve —la lista, la tabla, el panel— y desplaza ese."
    )


def seleccionar(elemento) -> str:
    """Elige un elemento; si no sabe hacerlo, lo pulsa.

    «Selecciona esta fila» y «pulsa esta fila» son la misma intención dicha de
    dos maneras, y muchas listas no publican `SelectionItem` aunque se puedan
    elegir perfectamente —la lista de chats de WhatsApp, sin ir más lejos—.
    Rechazarlo era devolver un error por una distinción que solo existe en la
    API.
    """
    UIA = _gen()
    patron = _patron(
        elemento, PATRON_SELECCIONAR, UIA.IUIAutomationSelectionItemPattern
    )
    if patron is not None:
        patron.Select()
        return "patrón seleccionar"
    return clic(elemento)


def expandir(elemento) -> str:
    UIA = _gen()
    patron = _patron(
        elemento, PATRON_EXPANDIR, UIA.IUIAutomationExpandCollapsePattern
    )
    if patron is None:
        raise ErrorUI("Este elemento no se puede expandir")
    patron.Expand()
    return "patrón expandir"


def contraer(elemento) -> str:
    UIA = _gen()
    patron = _patron(
        elemento, PATRON_EXPANDIR, UIA.IUIAutomationExpandCollapsePattern
    )
    if patron is None:
        raise ErrorUI("Este elemento no se puede contraer")
    patron.Collapse()
    return "patrón contraer"

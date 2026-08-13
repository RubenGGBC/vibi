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

# Por debajo de esto, el árbol de una ventana no se cree y se vuelve a pedir.
# Una ventana de verdad tiene barra de título, botones y contenido; con menos
# de treinta nodos, o es Chromium sin despertar o no publica nada.
MINIMO_CREIBLE = 30
ESPERA_DESPERTAR = 0.3
INTENTOS_DESPERTAR = 2


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
        if coleccion:
            for indice in range(coleccion.Length):
                try:
                    hijo = coleccion.GetElement(indice)
                    if not _merece_bajar(hijo, ventana):
                        continue
                    hijos.append(bajar(hijo, profundidad + 1))
                except Exception:
                    # Un elemento que muere a mitad no afecta a sus hermanos.
                    continue
        return _uno(fresco, tuple(hijos))

    raiz = elemento.BuildUpdatedCache(_peticion_nivel())
    return bajar(raiz, 0)


def _despertar(elemento, ventana: Rect) -> Nodo:
    """Pide el árbol, y si sale pequeño insiste antes de darlo por vacío.

    Chromium y Electron construyen el suyo solo cuando notan que alguien
    pregunta, y no lo tienen listo al instante: VS Code pasó de 14 nodos a
    2.468 entre dos consultas.
    """
    arbol = _traer_arbol(elemento, ventana)
    for _ in range(INTENTOS_DESPERTAR):
        if ui_tree.contar(arbol) >= MINIMO_CREIBLE:
            break
        time.sleep(ESPERA_DESPERTAR)
        arbol = _traer_arbol(elemento, ventana)
    return arbol


# ---------- Ventanas ----------

def _titulo(elemento) -> str:
    try:
        return elemento.CurrentName or ""
    except Exception:
        return ""


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


def _elemento(ventana: Ventana):
    """El elemento de UIA de una ventana, por su handle."""
    try:
        return _automation().ElementFromHandle(ventana.handle)
    except Exception as error:
        raise ErrorUI(
            f'No se pudo abrir «{ventana.titulo}»: {type(error).__name__}'
        ) from error


def elegir_ventana(titulo: str | None = None) -> tuple[Ventana, list[Ventana]]:
    """Qué ventana se mira, y cuáles son las demás."""
    abiertas = ventanas()
    if not abiertas:
        raise ErrorUI("No hay ninguna ventana abierta con título")

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
    titulo: str | None = None,
) -> tuple[Nodo, Rect, str, tuple[str, ...], str | None]:
    """El árbol crudo de una ventana, con su rectángulo y sus vecinas.

    Devuelve `(raiz, rect, titulo, otras, aviso)`. La poda, el colapso y los
    refs los pone `ui.py`: aquí solo se lee.
    """
    objetivo, abiertas = elegir_ventana(titulo)

    aviso = None
    if objetivo.minimizada:
        aviso = (
            f"Aviso: «{objetivo.titulo}» está minimizada, así que no se ve "
            "nada de ella. Restáurala para poder mirarla."
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
    try:
        arbol = _despertar(elemento, objetivo.rect)
    except Exception as error:
        # Le pasó a Opera y a WhatsApp al medir: ventanas que mueren entre
        # listarlas y consultarlas, o procesos a los que no se llega. Es un
        # árbol no disponible, no un fallo del agente.
        raise ErrorUI(
            f"No se pudo leer el árbol de «{objetivo.titulo}»: "
            f"{type(error).__name__}. Míralo con una captura."
        ) from error

    otras = tuple(
        v.titulo for v in abiertas if v.handle != objetivo.handle
    )[:8]
    # El rectángulo lo da user32 y no el árbol: una ventana minimizada publica
    # un elemento raíz sin geometría, y con él la poda se lo llevaría todo.
    return arbol, objetivo.rect, objetivo.titulo, otras, aviso


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


def enfocar(elemento) -> None:
    try:
        elemento.SetFocus()
    except Exception as error:
        raise ErrorUI(f"No se pudo enfocar: {error}") from error


def clic(elemento, boton: str = "left", veces: int = 1) -> str:
    """Pulsa, agotando los patrones del sistema antes de tocar el ratón.

    Invocar por patrón no depende de dónde esté la ventana, de que algo la
    tape ni de que el puntero llegue: es la aplicación ejecutando su propia
    acción. El ratón queda para lo que no expone ninguno y para el clic
    derecho, que no tiene equivalente en UIA.

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


def escribir(elemento, texto: str) -> str:
    """Pone texto en un campo, por patrón si se puede y tecleando si no."""
    UIA = _gen()
    valor = _patron(elemento, PATRON_VALOR, UIA.IUIAutomationValuePattern)
    if valor is not None:
        try:
            if valor.CurrentIsReadOnly:
                raise ErrorUI("Ese campo es de solo lectura")
        except AttributeError:
            pass
        valor.SetValue(texto)
        return "patrón valor"

    # Sin patrón hay que teclear, y para eso el foco tiene que estar dentro.
    enfocar(elemento)
    computer.teclear(texto)
    return "teclado"


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

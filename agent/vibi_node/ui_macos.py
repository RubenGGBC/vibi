"""El árbol de accesibilidad de macOS, vía la API de AX.

La otra mitad de `ui_windows`: misma interfaz, mismos `Nodo`, y todo lo demás
—podar, numerar, buscar, dibujar, el lote entero— compartido en `ui_tree` y
`ui.py`.

╔══════════════════════════════════════════════════════════════════════════╗
║  PROBADO CONTRA UN MAC EL 2026-09-09 (Darwin 25.5, pyobjc 12.2.2).       ║
║                                                                          ║
║  Hasta ese día estaba escrito solo contra la documentación. Lo que se    ║
║  encontró al probarlo, por orden de gravedad:                            ║
║                                                                          ║
║  1. La lista de aplicaciones venía de `NSWorkspace`, que **se congela**   ║
║     en un proceso sin run loop de Cocoa —que es exactamente lo que es    ║
║     este agente—. Todo lo que se abriera después de arrancar el nodo     ║
║     era invisible. Ver `_pids_con_ventanas`.                             ║
║  2. `_estado` marcaba «contraído» 240 de 277 nodos que no lo estaban.    ║
║  3. No había identificador de ventana, así que el teclado no sabía a     ║
║     quién iba y `activar` no activaba. Ver `_handle_de`.                 ║
║  4. Los menús del sistema no salían. Ver `_barra_de_menus`.              ║
║  5. `desplazar`, `valor_de` y `nombre_de` no existían.                   ║
╚══════════════════════════════════════════════════════════════════════════╝

**El permiso se comprueba antes de nada.** Sin Accesibilidad concedida, la API
no falla: devuelve árboles vacíos. Un árbol vacío es indistinguible de una app
que no publica nada, y manda a depurar al sitio equivocado, así que aquí se
pregunta primero y se dice la ruta exacta de Ajustes.
"""
from __future__ import annotations

import time
from dataclasses import replace

from . import computer, ui_tree
from .ui_tree import Nodo, Rect

ROL = "AXRole"
TITULO = "AXTitle"
VALOR = "AXValue"
DESCRIPCION = "AXDescription"
HIJOS = "AXChildren"
PADRE = "AXParent"
POSICION = "AXPosition"
TAMANO = "AXSize"
HABILITADO = "AXEnabled"
CON_FOCO = "AXFocused"
SELECCIONADO = "AXSelected"
EXPANDIDO = "AXExpanded"
VENTANAS = "AXWindows"
MINIMIZADA = "AXMinimized"
VENTANA_CON_FOCO = "AXFocusedWindow"
FRONTAL = "AXFrontmost"
BARRA_DE_MENUS = "AXMenuBar"
BARRA_VERTICAL = "AXVerticalScrollBar"
BARRA_HORIZONTAL = "AXHorizontalScrollBar"

ATRIBUTOS = (
    ROL, TITULO, VALOR, DESCRIPCION, POSICION, TAMANO,
    HABILITADO, CON_FOCO, SELECCIONADO, EXPANDIDO,
)

ACCION_PULSAR = "AXPress"
ACCION_MENU = "AXShowMenu"
ACCION_LEVANTAR = "AXRaise"

# Los roles que se pueden tocar aunque no declaren acciones.
ROLES_ACCIONABLES = frozenset({
    "AXButton", "AXPopUpButton", "AXMenuButton", "AXCheckBox",
    "AXRadioButton", "AXTextField", "AXTextArea", "AXSecureTextField",
    "AXComboBox", "AXLink", "AXMenuItem", "AXMenuBarItem", "AXSlider",
    "AXIncrementor", "AXRow", "AXCell", "AXDisclosureTriangle",
    "AXToolbarButton",
})

# Lo que cuenta como ventana. `AXWindows` de una aplicación trae también cosas
# que no lo son: Finder cuelga ahí el escritorio, que es un `AXScrollArea` que
# se llama «Finder» y que, por ser de las primeras aplicaciones que enumera el
# sistema, se llevaba el `capturar()` sin título cuando la de delante no tenía
# ninguna ventana. Windows tampoco ofrece el escritorio como ventana.
ROLES_VENTANA = frozenset({"AXWindow", "AXSheet", "AXDrawer"})

# Igual que en Windows: un árbol demasiado pequeño no se da por bueno a la
# primera. Aquí la causa habitual no es Chromium sino una app que aún está
# construyendo su ventana.
MINIMO_CREIBLE = 30
ESPERA_DESPERTAR = 0.3
INTENTOS_DESPERTAR = 2

# Lo que se le da al sistema para terminar de poner una ventana delante antes
# de preguntar si lo ha hecho. Mismo criterio que `ui_windows.activar`: la
# respuesta importa más que la acción, y preguntar a bocajarro contesta que no
# ha pasado nada porque la animación aún va por la mitad.
ESPERA_PRIMER_PLANO = 0.15

# Cuánto se espera a que una aplicación conteste. Sin esto, una app colgada
# congela el lote entero: AX bloquea al que pregunta hasta que el otro
# responda, y el presupuesto de `ui.ejecutar_lote` son 30 s para todo.
TIMEOUT_AX = 1.5

# Hasta dónde se baja. AX no tiene el equivalente del CacheRequest de UIA para
# subárboles enteros, así que el recorrido va nivel a nivel y una jerarquía
# patológica podría no terminar nunca.
MAX_PROFUNDIDAD = 60

# Cuántas ventanas se recuerdan con su identificador. Ver `_handle_de`.
MAX_HANDLES = 128


class ErrorUI(Exception):
    pass


def _api():
    try:
        import ApplicationServices
        import AppKit
    except ImportError as error:  # pragma: no cover - depende de la máquina
        raise ErrorUI(
            "Falta pyobjc en esta máquina. Instálalo con "
            "«pip install -r agent/requirements.txt»."
        ) from error
    return ApplicationServices, AppKit


def _exigir_permiso() -> None:
    servicios, _ = _api()
    if servicios.AXIsProcessTrusted():
        return
    raise ErrorUI(
        "Vibi no tiene permiso de Accesibilidad en este Mac, y sin él el "
        "sistema devuelve ventanas vacías en vez de un error. Concédelo en "
        "Ajustes del Sistema › Privacidad y seguridad › Accesibilidad, "
        "marcando la aplicación desde la que corre el agente, y vuelve a "
        "intentarlo."
    )


def disponible() -> bool:
    try:
        _api()
        return True
    except Exception:
        return False


# ---------- Lectura ----------

def _valor(elemento, atributo):
    servicios, _ = _api()
    error, valor = servicios.AXUIElementCopyAttributeValue(
        elemento, atributo, None
    )
    if error != 0:
        return None
    return _limpio(valor)


def _es_error(valor) -> bool:
    """Si lo que ha vuelto es el marcador de «este elemento no tiene eso».

    AX no contesta `None` a un atributo que no existe: devuelve un `AXValue`
    de tipo `kAXValueAXErrorType` envolviendo el código del error. Antes se
    intentaba reconocerlo por el nombre de la clase (`AXValueError`), que no
    es el que usa pyobjc —los envuelve todos en `AXValueRef`—, así que el
    marcador se colaba en el árbol y solo lo paraban, de casualidad, los
    `isinstance(..., str)` de más abajo.
    """
    servicios, _ = _api()
    if valor is None or isinstance(valor, (str, bool, int, float)):
        return valor is None
    try:
        return servicios.AXValueGetType(valor) == servicios.kAXValueAXErrorType
    except Exception:
        return False


def _limpio(valor):
    return None if _es_error(valor) else valor


def _varios(elemento, atributos) -> dict:
    """Varios atributos en una llamada, que es lo que hace esto viable.

    Es el equivalente del `CacheRequest` de UIA: sin él habría un salto entre
    procesos por atributo y por elemento, y en Windows eso medía 3 segundos
    por ventana. Medido aquí el 2026-09-09: 553 elementos en 63 ms.
    """
    servicios, _ = _api()
    error, valores = servicios.AXUIElementCopyMultipleAttributeValues(
        elemento, atributos, 0, None
    )
    if error != 0 or valores is None:
        return {}
    salida = {}
    for nombre, valor in zip(atributos, valores):
        if _es_error(valor):
            continue
        salida[nombre] = valor
    return salida


def _declarados(elemento) -> frozenset[str]:
    """Qué atributos dice tener este elemento. Ver `_estado`.

    Cuesta una llamada más por elemento: 41 ms sobre los 553 nodos de una
    ventana de Safari, contra los 63 ms que ya costaba leerles los valores.
    """
    servicios, _ = _api()
    try:
        error, nombres = servicios.AXUIElementCopyAttributeNames(elemento, None)
    except Exception:
        return frozenset()
    if error != 0 or nombres is None:
        return frozenset()
    return frozenset(str(n) for n in nombres)


def _texto(datos, *claves) -> str:
    for clave in claves:
        valor = datos.get(clave)
        if isinstance(valor, str) and valor.strip():
            return valor
    return ""


def _punto_y_tamano(datos) -> Rect:
    servicios, _ = _api()
    posicion = datos.get(POSICION)
    tamano = datos.get(TAMANO)
    if posicion is None or tamano is None:
        return ui_tree.RECT_NULO
    try:
        ok_p, punto = servicios.AXValueGetValue(
            posicion, servicios.kAXValueCGPointType, None
        )
        ok_t, medida = servicios.AXValueGetValue(
            tamano, servicios.kAXValueCGSizeType, None
        )
    except Exception:
        return ui_tree.RECT_NULO
    if not (ok_p and ok_t):
        return ui_tree.RECT_NULO
    return Rect(
        int(punto.x),
        int(punto.y),
        int(punto.x + medida.width),
        int(punto.y + medida.height),
    )


def _unir(uno: Rect, otro: Rect) -> Rect:
    if uno.vacio:
        return otro
    if otro.vacio:
        return uno
    return Rect(
        min(uno.izquierda, otro.izquierda),
        min(uno.arriba, otro.arriba),
        max(uno.derecha, otro.derecha),
        max(uno.abajo, otro.abajo),
    )


def _estado(datos, declarados: frozenset[str], rol_ax: str) -> frozenset[str]:
    """Qué le pasa a este elemento, contando solo lo que de verdad dice.

    **Un `False` de AX no significa «no»: significa casi siempre «no tengo ese
    atributo».** Medido el 2026-09-09 sobre una ventana de Safari: 553
    elementos, de los que **uno solo** declara `AXExpanded` en
    `AXUIElementCopyAttributeNames`, y sin embargo los 553 contestan `False`
    cuando se les pregunta —sin error, con código 0—. Leído a la brava, el
    árbol salía con 240 de 277 nodos marcados «(contraído)»: un ruido que
    doblaba el texto que veía el modelo y que además mentía, porque le decía
    que cada enlace de una página escondía algo dentro que había que expandir.

    Windows no tiene este problema porque allí las capacidades son patrones y
    un patrón que no está no se puede preguntar. Aquí hay que preguntarlo
    aparte, y por eso `_declarados` existe.

    Lo mismo con `desactivado`, con un filtro añadido: solo se anota en lo que
    se podría tocar. WebKit publica su texto estático como `AXEnabled: False`
    —es cierto, un párrafo no se pulsa— y marcarlos todos era repetir 86 veces
    algo que el rol ya dice.
    """
    estados = set()
    if (
        HABILITADO in declarados
        and datos.get(HABILITADO) is False
        and rol_ax in ROLES_ACCIONABLES
    ):
        estados.add("desactivado")
    # Los `True` sí valen tal cual: nadie contesta que sí a algo que no tiene.
    if datos.get(CON_FOCO) is True:
        estados.add("con foco")
    if datos.get(SELECCIONADO) is True:
        estados.add("seleccionado")
    if EXPANDIDO in declarados:
        expandido = datos.get(EXPANDIDO)
        if expandido is True:
            estados.add("expandido")
        elif expandido is False:
            estados.add("contraído")
    return frozenset(estados)


def _valor_texto(datos) -> str | None:
    crudo = datos.get(VALOR)
    if isinstance(crudo, str):
        return ui_tree.recortar_valor(crudo)
    if isinstance(crudo, bool):
        return "sí" if crudo else "no"
    if isinstance(crudo, (int, float)):
        return str(crudo)
    return None


def _convertir(
    elemento,
    camino: tuple,
    profundidad: int = 0,
    solo_visibles: bool = False,
) -> Nodo:
    """De elemento de AX a `Nodo`, y sus hijos con él.

    `solo_visibles` corta la bajada en cuanto un elemento no ocupa sitio en
    pantalla. Es para los menús: ver `_barra_de_menus`.
    """
    datos = _varios(elemento, ATRIBUTOS)
    rol_ax = _texto(datos, ROL) or "AXUnknown"
    rect = _punto_y_tamano(datos)

    hijos = []
    if profundidad < MAX_PROFUNDIDAD and not (solo_visibles and rect.vacio):
        crios = _valor(elemento, HIJOS) or []
        for indice, hijo in enumerate(crios):
            try:
                hijos.append(
                    _convertir(
                        hijo, camino + (indice,), profundidad + 1, solo_visibles
                    )
                )
            except Exception:
                # Un elemento que muere a mitad no se lleva a sus hermanos.
                continue

    protegido = rol_ax == "AXSecureTextField"
    estado = _estado(datos, _declarados(elemento), rol_ax)
    if protegido:
        estado = estado | {"protegido"}
    return Nodo(
        rol=ui_tree.rol_ax(rol_ax),
        nombre=_texto(datos, TITULO, DESCRIPCION),
        valor=None if protegido else _valor_texto(datos),
        estado=estado,
        rect=rect,
        accionable=rol_ax in ROLES_ACCIONABLES,
        hijos=tuple(hijos),
        nativo=elemento,
        # AX no tiene nada como el RuntimeId de UIA, así que la identidad es
        # dónde estaba: el proceso y la ruta de índices desde la ventana.
        identidad=camino,
    )


# ---------- Ventanas y su identificador ----------

# `handle` -> (elemento de la ventana, pid). Ver `_handle_de`.
_HANDLES: dict[int, tuple[object, int]] = {}
_ULTIMO_HANDLE = 0


def olvidar_ventanas() -> None:
    """Tira los identificadores. Para las pruebas y para cuando cambia el nodo."""
    global _ULTIMO_HANDLE
    _HANDLES.clear()
    _ULTIMO_HANDLE = 0


def _handle_de(elemento, pid: int) -> int:
    """El número con el que `ui.py` se refiere a esta ventana, estable.

    **Windows tiene `HWND` y macOS no tiene nada equivalente en la API
    pública**, y de esa falta salían dos fallos a la vez. El primero es el que
    `ui_windows` ya arregló y aquí seguía vivo: `ui.ejecutar_lote` fija la
    ventana al empezar y relee contra el identificador, porque el título
    cambia solo —Spotify con la canción, un navegador con la pestaña—, y sin
    identificador cada relectura volvía a buscar por título y el lote se moría
    a mitad. El segundo es peor: sin identificador, `ui.entrada_global_llega`
    no puede comparar nada y contesta que sí siempre, así que un `escribir`
    sin `ref` o un `tecla` sobre una ventana de fondo se iban a la que
    estuviera delante en vez de ser rechazados. Es exactamente el WhatsApp
    tecleado sobre un vídeo de YouTube que documenta `tests/test_ui_foco.py`.

    Lo que se hace en su lugar es apuntar la ventana aquí y devolver un número
    propio. Vale porque los `AXUIElementRef` de una misma ventana comparan
    iguales aunque se hayan pedido por caminos distintos —comprobado el
    2026-09-09: la ventana que sale de `AXWindows` y la que sale de
    `AXFocusedWindow` son `==`—, así que la búsqueda por igualdad reconoce a
    la misma ventana entre lecturas.
    """
    global _ULTIMO_HANDLE
    for handle, (guardado, suyo) in _HANDLES.items():
        if suyo != pid:
            continue
        try:
            if guardado == elemento:
                return handle
        except Exception:
            continue
    if len(_HANDLES) >= MAX_HANDLES:
        _podar_handles()
    _ULTIMO_HANDLE += 1
    _HANDLES[_ULTIMO_HANDLE] = (elemento, pid)
    return _ULTIMO_HANDLE


def _podar_handles() -> None:
    """Quita las ventanas que ya no existen. Una ventana muerta no contesta."""
    for handle, (elemento, _) in list(_HANDLES.items()):
        if _valor(elemento, ROL) is None:
            _HANDLES.pop(handle, None)


# La capa en la que viven las ventanas normales. Por encima están los menús
# desplegados, el Dock, las notificaciones y los paneles del sistema, que no
# son de nadie y no se miran.
CAPA_NORMAL = 0


def _lista_de_ventanas(opciones) -> list:
    """Lo que el servidor de ventanas ve ahora mismo, de delante a atrás.

    Nada de esto necesita permiso: el título de la ventana (`kCGWindowName`)
    sí pediría Grabación de Pantalla, y por eso no se usa —el título se lee
    por AX, que ya tiene su permiso—. El proceso dueño, la capa y el orden
    son públicos.
    """
    servicios, _ = _api()
    info = servicios.CGWindowListCopyWindowInfo(
        opciones | servicios.kCGWindowListExcludeDesktopElements,
        servicios.kCGNullWindowID,
    )
    return [
        v for v in (info or [])
        if int(v.get("kCGWindowLayer", 1)) == CAPA_NORMAL
    ]


def _pids_con_ventanas() -> list[int]:
    """Qué procesos tienen ventanas, preguntado en vivo.

    **Esto es el fallo de raíz del módulo, y por qué en Windows funcionaba
    todo y aquí no funcionaba nada.** Antes la lista salía de
    `NSWorkspace.sharedWorkspace().runningApplications()`, que es una
    colección que Cocoa mantiene al día **con notificaciones que solo se
    entregan cuando corre un run loop de AppKit**. El nodo es un proceso de
    asyncio sin nada de eso, así que esa lista se queda como estaba al
    arrancar el agente: para siempre.

    Medido el 2026-09-09 sobre un proceso sin run loop: se abrió la
    Calculadora, se dejó 12 s delante y se cerró, y `runningApplications()`
    devolvió las mismas 7 aplicaciones todo el rato,
    `frontmostApplication()` siguió diciendo «Safari» mientras la Calculadora
    estaba delante, y `ventanas()` siguió devolviendo las mismas 6 ventanas.
    Traducido a lo que ve quien usa Vibi: **cualquier cosa abierta después de
    encender el nodo no existe**, y `devices_ui_snapshot` contesta «no hay
    ninguna ventana que se llame X» enseñando la lista de lo que había al
    arrancar. En Windows `EnumWindows` es una llamada al sistema y siempre
    dice la verdad, de ahí la diferencia.

    `CGWindowListCopyWindowInfo` sí es una pregunta de verdad al servidor de
    ventanas, sin colección que refrescar. Con `kCGWindowListOptionAll` entran
    también las minimizadas, que están fuera de pantalla pero siguen siendo
    ventanas que se pueden nombrar.
    """
    servicios, _ = _api()
    vistos: list[int] = []
    for ventana in _lista_de_ventanas(servicios.kCGWindowListOptionAll):
        pid = int(ventana.get("kCGWindowOwnerPID") or 0)
        if pid and pid not in vistos:
            vistos.append(pid)
    return vistos


def _apps():
    """Las aplicaciones con ventanas y su elemento de AX.

    `runningApplicationWithProcessIdentifier_` sí contesta en vivo —es una
    búsqueda por pid, no la colección congelada de `_pids_con_ventanas`—, y
    hace falta para dos cosas: descartar los procesos de apoyo (los
    `AutoFill`, los `ViewService` y demás, que tienen ventanas y no salen en
    el Dock) y saber cómo se llama la aplicación.
    """
    _, appkit = _api()
    for pid in _pids_con_ventanas():
        app = appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
            pid
        )
        # 0 es NSApplicationActivationPolicyRegular: las que salen en el Dock.
        if app is None or app.activationPolicy() != 0:
            continue
        yield app, _referencia_de_app(pid)


def ventanas() -> list[tuple[str, object, bool, int, int]]:
    """`(titulo, elemento, minimizada, pid, handle)` de cada ventana abierta."""
    _exigir_permiso()
    salida = []
    for app, referencia in _apps():
        try:
            suyas = _valor(referencia, VENTANAS) or []
        except Exception:
            continue
        pid = int(app.processIdentifier())
        for ventana in suyas:
            datos = _varios(ventana, (ROL, TITULO))
            if _texto(datos, ROL) not in ROLES_VENTANA:
                continue
            titulo = _texto(datos, TITULO)
            if not titulo.strip():
                titulo = str(app.localizedName() or "")
            if not titulo.strip():
                continue
            salida.append((
                titulo,
                ventana,
                bool(_valor(ventana, MINIMIZADA)),
                pid,
                _handle_de(ventana, pid),
            ))
    return salida


def _app_en_primer_plano() -> int:
    """El pid de quien está delante. La lista viene ordenada, el primero manda.

    Tampoco esto podía salir de `NSWorkspace.frontmostApplication()`: se
    congela igual que la lista de aplicaciones, y congelado envenenaba tres
    cosas a la vez —qué ventana coge `capturar()` sin título, el aviso de «no
    está delante», y si `activar` había funcionado o no—.
    """
    servicios, _ = _api()
    for ventana in _lista_de_ventanas(servicios.kCGWindowListOptionOnScreenOnly):
        return int(ventana.get("kCGWindowOwnerPID") or 0)
    return 0


def nombre_app_en_primer_plano() -> str:
    """Nombre de la app frontal sin recorrer AX ni pedir permisos.

    Lo usa la sonda del relevo cada 0,75 s, y por eso no toca AX: mirarlo por
    ahí dispararía el permiso de Accesibilidad sin que nadie lo haya pedido.
    """
    try:
        servicios, _ = _api()
        for ventana in _lista_de_ventanas(
            servicios.kCGWindowListOptionOnScreenOnly
        ):
            return str(ventana.get("kCGWindowOwnerName") or "")
        return ""
    except Exception:
        return ""


def _referencia_de_app(pid: int):
    servicios, _ = _api()
    referencia = servicios.AXUIElementCreateApplication(pid)
    try:
        servicios.AXUIElementSetMessagingTimeout(referencia, TIMEOUT_AX)
    except Exception:
        pass
    return referencia


def handle_en_primer_plano() -> int:
    """La ventana que se va a llevar el teclado y el ratón, o 0 si no se sabe.

    Es la mitad que le faltaba a `ui.entrada_global_llega`, que sin esta
    función devolvía `True` a ciegas y dejaba pasar la entrada global sobre
    ventanas de fondo. Nunca levanta: es una comprobación de seguridad y un
    fallo suyo no debe impedir mirar una ventana.
    """
    try:
        pid = _app_en_primer_plano()
        if not pid:
            return 0
        ventana = _valor(_referencia_de_app(pid), VENTANA_CON_FOCO)
        if ventana is None:
            return 0
        return _handle_de(ventana, pid)
    except Exception:
        return 0


def activar(handle: int) -> bool:
    """Trae esa ventana al frente, y dice si de verdad se ha quedado ahí.

    Antes ni existía, y por eso el paso `activar` de un lote no hacía nada en
    un Mac: `ui._actuar` preguntaba por ella con `getattr` y, al no
    encontrarla, o daba «este sistema no sabe» o —peor— ni llegaba, porque sin
    `handle` la comprobación previa creía que la ventana ya estaba delante.

    Son dos pasos y hacen falta los dos: `AXRaise` sube la ventana dentro de
    su aplicación, y poner `AXFrontmost` sube la aplicación por encima de las
    demás. Solo el primero deja la ventana delante de sus hermanas pero detrás
    de la app que tenga el foco. `activateWithOptions_` va detrás como
    respaldo, por si la aplicación no atiende AX.
    """
    _, appkit = _api()
    entrada = _HANDLES.get(int(handle or 0))
    if entrada is None:
        return False
    ventana, pid = entrada
    try:
        servicios, _ = _api()
        if _valor(ventana, MINIMIZADA) is True:
            # Una ventana en el Dock puede subir al frente y quedarse
            # enrollada, y entonces el árbol vuelve vacío. Mismo caso que el
            # `SW_RESTORE` de Windows.
            servicios.AXUIElementSetAttributeValue(ventana, MINIMIZADA, False)
        if _acepta(ventana, ACCION_LEVANTAR):
            try:
                _hacer(ventana, ACCION_LEVANTAR)
            except ErrorUI:
                pass
        # `AXFrontmost` es la vía de accesibilidad y va primero: ya tenemos
        # ese permiso, y no depende de que el proceso sea una aplicación de
        # interfaz. `activateWithOptions_` queda de respaldo.
        servicios.AXUIElementSetAttributeValue(
            _referencia_de_app(pid), FRONTAL, True
        )
        corriendo = appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
            pid
        )
        if corriendo is not None:
            corriendo.activateWithOptions_(
                getattr(appkit, "NSApplicationActivateIgnoringOtherApps", 2)
            )
        time.sleep(ESPERA_PRIMER_PLANO)
        return handle_en_primer_plano() == int(handle)
    except Exception:
        return False


def _barra_de_menus(pid: int) -> Nodo | None:
    """Los menús del sistema de esa aplicación, colgados de su ventana.

    **En macOS los menús no están en la ventana, están en la aplicación**, y
    esa diferencia dejaba fuera la mitad del catálogo. `capturar` lee el árbol
    de un `AXWindow`, y «Archivo › Guardar como» —el ejemplo con el que está
    escrito el docstring de `ui.py`— no cuelga de ahí sino del `AXMenuBar` del
    proceso. En Windows la barra es parte de la ventana y sale sola, así que
    el mismo lote funcionaba allí y aquí decía que no existía tal menú.

    Se lee con `solo_visibles` porque un menú cerrado publica sus opciones
    igual: la barra de Safari son 750 nodos, de los que 741 son opciones de
    menús que nadie ha abierto y que el sistema sitúa fuera de la pantalla
    (rectángulo vacío). Parar ahí deja los 9 nombres de la barra por 20 ms en
    vez de 214, y en cuanto el modelo pulsa «Archivo» el menú se abre, pasa a
    tener sitio en pantalla y la siguiente lectura sí baja dentro.
    """
    barra = _valor(_referencia_de_app(pid), BARRA_DE_MENUS)
    if barra is None:
        return None
    try:
        return _convertir(barra, (pid, "menus"), solo_visibles=True)
    except Exception:
        return None


def _despertar(ventana, pid: int) -> Nodo:
    arbol = _convertir(ventana, (pid,))
    for _ in range(INTENTOS_DESPERTAR):
        if ui_tree.contar(arbol) >= MINIMO_CREIBLE:
            break
        time.sleep(ESPERA_DESPERTAR)
        arbol = _convertir(ventana, (pid,))
    return arbol


def capturar(
    titulo: str | None = None, handle: int = 0
) -> tuple[Nodo, Rect, str, tuple[str, ...], str | None, int]:
    """El árbol crudo de una ventana, con su rectángulo, sus vecinas y su id.

    **Con `handle` no se vuelve a mirar el título.** Es lo que pide
    `ui.ejecutar_lote` para que un lote no se rompa cuando la ventana se
    retitula a mitad, y hasta ahora este backend lo aceptaba y lo tiraba
    (`del handle`), así que en Mac seguía pasando lo que en Windows ya no.
    """
    abiertas = ventanas()

    objetivo = None
    if handle:
        objetivo = next((v for v in abiertas if v[4] == int(handle)), None)
        if objetivo is None:
            raise ErrorUI(
                "La ventana que estabas mirando ya no está abierta. Vuelve a "
                "mirar para ver qué hay ahora."
            )
    if objetivo is None and not abiertas:
        raise ErrorUI("No hay ninguna ventana abierta con título")

    if objetivo is None and titulo and titulo.strip():
        buscado = ui_tree.normalizar(titulo)
        exactas = [v for v in abiertas if ui_tree.normalizar(v[0]) == buscado]
        parciales = [v for v in abiertas if buscado in ui_tree.normalizar(v[0])]
        elegidas = exactas or parciales
        if not elegidas:
            nombres = ", ".join(f'"{v[0]}"' for v in abiertas[:12])
            raise ErrorUI(
                f"No hay ninguna ventana que se llame «{titulo}». "
                f"Abiertas: {nombres}"
            )
        objetivo = elegidas[0]
    if objetivo is None:
        delante = _app_en_primer_plano()
        objetivo = next(
            (v for v in abiertas if v[3] == delante and not v[2]), abiertas[0]
        )

    nombre, elemento, minimizada, pid, suyo = objetivo
    en_primer_plano = pid == _app_en_primer_plano()

    aviso = None
    if minimizada:
        aviso = (
            f"Aviso: «{nombre}» está en el Dock, así que no se ve nada de "
            "ella. Restáurala para poder mirarla."
        )
    elif not en_primer_plano:
        aviso = (
            f"Aviso: «{nombre}» no está delante, así que puede aparecer "
            "incompleta y sus menús no salen. Usa un paso `activar` para "
            "ponerla en primer plano."
        )

    try:
        arbol = _despertar(elemento, pid)
    except Exception as error:
        raise ErrorUI(
            f"No se pudo leer el árbol de «{nombre}»: {type(error).__name__}. "
            "Míralo con una captura."
        ) from error

    marco = arbol.rect
    # La barra de menús solo se enseña cuando es la que se ve. macOS dibuja la
    # de la aplicación que está delante, así que la de una app de fondo se
    # publica igual pero no está en pantalla: ofrecerla sería ofrecer algo que
    # no se puede pulsar.
    if en_primer_plano and not minimizada:
        barra = _barra_de_menus(pid)
        if barra is not None and not barra.rect.vacio:
            arbol = replace(arbol, hijos=(barra,) + arbol.hijos)
            # El marco es lo que `ui_tree.podar` usa para decidir qué se ve, y
            # la barra está fuera de la ventana: sin ensancharlo se podaría
            # entera justo después de haberla leído.
            marco = _unir(marco, barra.rect)

    otras = tuple(v[0] for v in abiertas if v[0] != nombre)[:8]
    return arbol, marco, nombre, otras, aviso, suyo


# ---------- Revalidación ----------

def sigue_vivo(nativo, huella: ui_tree.Huella) -> bool:
    """Si el `ref` sigue señalando lo mismo.

    Sin `RuntimeId` que comparar, lo que queda es preguntar de nuevo: un
    elemento muerto devuelve error en cualquier atributo, y uno reciclado
    contesta con otro rol u otro nombre.
    """
    if nativo is None:
        return False
    try:
        datos = _varios(nativo, (ROL, TITULO, DESCRIPCION))
    except Exception:
        return False
    if not datos:
        return False
    if ui_tree.rol_ax(_texto(datos, ROL) or "AXUnknown") != huella.rol:
        return False
    return _texto(datos, TITULO, DESCRIPCION) == huella.nombre


# ---------- Acciones ----------

def _hacer(elemento, accion: str) -> None:
    servicios, _ = _api()
    error = servicios.AXUIElementPerformAction(elemento, accion)
    if error != 0:
        raise ErrorUI(f"El sistema rechazó «{accion}» (error {error})")


def _acepta(elemento, accion: str) -> bool:
    servicios, _ = _api()
    try:
        error, acciones = servicios.AXUIElementCopyActionNames(elemento, None)
    except Exception:
        return False
    return error == 0 and acciones is not None and accion in acciones


def _centro(elemento) -> tuple[int, int] | None:
    rect = _punto_y_tamano(_varios(elemento, (POSICION, TAMANO)))
    if rect.vacio:
        return None
    return (
        (rect.izquierda + rect.derecha) // 2,
        (rect.arriba + rect.abajo) // 2,
    )


def nombre_de(elemento) -> str:
    """Cómo se llama ese elemento ahora mismo, leído en vivo.

    Lo usa `ui.ejecutar_lote` para saber qué campo buscar en el árbol de
    después de escribir. Sin esta función el lote no podía comprobar nada y
    daba todo por bueno: ver `valor_de`.
    """
    try:
        datos = _varios(elemento, (TITULO, DESCRIPCION))
    except Exception:
        return ""
    return _texto(datos, TITULO, DESCRIPCION)


def valor_de(elemento) -> str | None:
    """El texto que tiene ese elemento, en vivo. `None` si no lo publica.

    Es lo que usa `ui._verificar_escritura` para releer la ventana y ver si el
    texto entró de verdad. Al no existir, ese control devolvía siempre «sin
    comprobar: el campo no publica su valor» en Mac, que es la puerta por la
    que se cuela el «ya te lo he enviado» de algo que no se escribió —el
    motivo entero por el que la comprobación existe, ver su docstring—.
    """
    try:
        crudo = _valor(elemento, VALOR)
    except Exception:
        return None
    return crudo if isinstance(crudo, str) else None


def enfocar(elemento) -> None:
    servicios, _ = _api()
    error = servicios.AXUIElementSetAttributeValue(elemento, CON_FOCO, True)
    if error != 0:
        raise ErrorUI(f"No se pudo enfocar (error {error})")


def clic(
    elemento, boton: str = "left", veces: int = 1, entrada_global: bool = True
) -> str:
    """Pulsa, prefiriendo la acción del sistema al ratón.

    `entrada_global` llega en `False` cuando la ventana no está delante y el
    ratón caería en otra. Desde que `handle_en_primer_plano` existe, ese
    `False` llega de verdad en un Mac: antes `ui.entrada_global_llega` no
    tenía con qué comparar y contestaba que sí siempre.
    """
    if boton == "right":
        if _acepta(elemento, ACCION_MENU):
            _hacer(elemento, ACCION_MENU)
            return "acción menú"
    elif veces == 1 and _acepta(elemento, ACCION_PULSAR):
        _hacer(elemento, ACCION_PULSAR)
        return "acción pulsar"

    if not entrada_global:
        raise ErrorUI(
            "Ese elemento no admite ninguna acción del sistema y su ventana "
            "no está delante: un clic por coordenadas caería en otra. Ponla "
            "delante con un paso `activar`."
        )

    punto = _centro(elemento)
    if punto is None:
        raise ErrorUI(
            "Este elemento no admite ninguna acción y no tiene sitio en "
            "pantalla donde pinchar"
        )
    computer.clic_escritorio(punto[0], punto[1], boton=boton, veces=veces)
    return "ratón"


def escribir(elemento, texto: str, entrada_global: bool = True) -> str:
    """Pone texto en un campo, y comprueba que se haya quedado.

    Mismo motivo que en Windows: poner el atributo puede devolver éxito sin que
    el campo cambie, y un `ok` que no significa nada acaba en un «ya está
    hecho» que no es verdad. Ver el docstring de `ui_windows.escribir`.
    """
    servicios, _ = _api()
    error = servicios.AXUIElementSetAttributeValue(elemento, VALOR, texto)
    if error == 0:
        quedo = _valor(elemento, VALOR)
        if quedo is None:
            return "atributo valor (sin poder comprobarlo)"
        if " ".join(str(quedo).split()) and (
            " ".join(texto.split()) in " ".join(str(quedo).split())
        ):
            return "atributo valor"
    if not entrada_global:
        raise ErrorUI(
            "Ese campo no se ha quedado con el texto y hay que teclearlo, "
            "pero su ventana no está delante: lo escrito acabaría en otra. "
            "Ponla delante con un paso `activar`."
        )
    enfocar(elemento)
    computer.teclear(texto)
    return "teclado"


# Hacia dónde mira cada dirección: qué barra la mueve, en qué sentido y qué
# manda la rueda del ratón cuando la barra no se deja.
DESPLAZAMIENTOS = {
    "abajo": (BARRA_VERTICAL, 1, "down"),
    "arriba": (BARRA_VERTICAL, -1, "up"),
    "derecha": (BARRA_HORIZONTAL, 1, "right"),
    "izquierda": (BARRA_HORIZONTAL, -1, "left"),
}

# Cuánto mueve un paso de la barra, en tanto por uno del recorrido total.
PASO_BARRA = 0.08

# Cuántos padres se suben buscando el panel que sí se desplaza. Quien dice
# «baja esa lista» señala un elemento de dentro, no el contenedor.
MAX_SUBIDAS = 8

MAX_DESPLAZAMIENTOS = 20


def _barra_que_mueve(elemento, atributo):
    actual = elemento
    for _ in range(MAX_SUBIDAS):
        if actual is None:
            return None
        barra = _valor(actual, atributo)
        if barra is not None:
            return barra
        actual = _valor(actual, PADRE)
    return None


def desplazar(elemento, direccion: str = "abajo", veces: int = 1) -> str:
    """Mueve una lista o un panel. Antes no existía y el paso daba error.

    `ui._actuar` busca esta función con `getattr` y, al no encontrarla,
    contestaba «este sistema no sabe desplazar por patrón todavía»: en un Mac
    el paso `desplazar` de un lote no funcionaba nunca.

    **AX no tiene el `ScrollPattern` de UIA**, así que no hay forma de pedirle
    a una lista que se mueva sola. Lo más parecido es la barra de
    desplazamiento, que publica su posición como un número de 0 a 1 y admite
    que se la cambien: eso es la aplicación desplazándose a sí misma, no
    depende del puntero y funciona con la ventana detrás. Cuando la barra no
    se deja —el contenido web no suele exponerla— queda la rueda del ratón,
    que va a lo que haya bajo el puntero y por tanto necesita la ventana
    visible: por eso se intenta en este orden y no al revés.
    """
    servicios, _ = _api()
    if direccion not in DESPLAZAMIENTOS:
        raise ErrorUI(
            f"No sé desplazar «{direccion}». Las direcciones son: "
            f"{', '.join(DESPLAZAMIENTOS)}."
        )
    atributo, sentido, rueda = DESPLAZAMIENTOS[direccion]
    pasos = max(1, min(int(veces or 1), MAX_DESPLAZAMIENTOS))

    barra = _barra_que_mueve(elemento, atributo)
    if barra is not None:
        actual = _valor(barra, VALOR)
        if isinstance(actual, (int, float)) and not isinstance(actual, bool):
            antes = float(actual)
            destino = min(1.0, max(0.0, antes + sentido * PASO_BARRA * pasos))
            if abs(destino - antes) > 1e-9:
                error = servicios.AXUIElementSetAttributeValue(
                    barra, VALOR, destino
                )
                despues = _valor(barra, VALOR)
                if error == 0 and isinstance(despues, (int, float)):
                    if abs(float(despues) - antes) > 1e-6:
                        return "barra de desplazamiento"

    punto = _centro(elemento)
    if punto is None:
        raise ErrorUI(
            "Eso no se desplaza por su barra y no tiene sitio en pantalla "
            "donde poner la rueda. Busca el panel que lo envuelve."
        )
    computer.desplazar_escritorio(punto[0], punto[1], rueda, pasos)
    return "rueda del ratón"


def seleccionar(elemento) -> str:
    servicios, _ = _api()
    if _acepta(elemento, ACCION_PULSAR):
        _hacer(elemento, ACCION_PULSAR)
        return "acción pulsar"
    error = servicios.AXUIElementSetAttributeValue(elemento, SELECCIONADO, True)
    if error != 0:
        raise ErrorUI("Este elemento no se puede seleccionar")
    return "atributo seleccionado"


def _plegar(elemento, abierto: bool, verbo: str) -> str:
    servicios, _ = _api()
    error = servicios.AXUIElementSetAttributeValue(elemento, EXPANDIDO, abierto)
    if error != 0:
        raise ErrorUI(f"Este elemento no se puede {verbo}")
    return "atributo expandido"


def expandir(elemento) -> str:
    return _plegar(elemento, True, "expandir")


def contraer(elemento) -> str:
    return _plegar(elemento, False, "contraer")

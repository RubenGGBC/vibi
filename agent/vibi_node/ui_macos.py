"""El árbol de accesibilidad de macOS, vía la API de AX.

La otra mitad de `ui_windows`: misma interfaz, mismos `Nodo`, y todo lo demás
—podar, numerar, buscar, dibujar, el lote entero— compartido en `ui_tree` y
`ui.py`.

╔══════════════════════════════════════════════════════════════════════════╗
║  ESTE MÓDULO NO SE HA PROBADO NUNCA CONTRA UN MAC.                       ║
║                                                                          ║
║  Está escrito contra la documentación de la API de accesibilidad, por    ║
║  decisión explícita del dueño del proyecto el 2026-08-13: no hay ningún  ║
║  Mac en la malla de nodos con el que comprobarlo. Windows sí se probó    ║
║  contra apps reales.                                                     ║
║                                                                          ║
║  Lo más probable que falle, por orden: el mapa de roles, la conversión   ║
║  de AXValue a posición y tamaño, y el comportamiento de                  ║
║  AXUIElementCopyMultipleAttributeValues con elementos que no tienen      ║
║  todos los atributos pedidos.                                            ║
╚══════════════════════════════════════════════════════════════════════════╝

**El permiso se comprueba antes de nada.** Sin Accesibilidad concedida, la API
no falla: devuelve árboles vacíos. Un árbol vacío es indistinguible de una app
que no publica nada, y manda a depurar al sitio equivocado, así que aquí se
pregunta primero y se dice la ruta exacta de Ajustes.
"""
from __future__ import annotations

import time

from . import computer, ui_tree
from .ui_tree import Nodo, Rect

ROL = "AXRole"
TITULO = "AXTitle"
VALOR = "AXValue"
DESCRIPCION = "AXDescription"
HIJOS = "AXChildren"
POSICION = "AXPosition"
TAMANO = "AXSize"
HABILITADO = "AXEnabled"
CON_FOCO = "AXFocused"
SELECCIONADO = "AXSelected"
EXPANDIDO = "AXExpanded"
VENTANAS = "AXWindows"
MINIMIZADA = "AXMinimized"

ATRIBUTOS = (
    ROL, TITULO, VALOR, DESCRIPCION, POSICION, TAMANO,
    HABILITADO, CON_FOCO, SELECCIONADO, EXPANDIDO,
)

ACCION_PULSAR = "AXPress"
ACCION_MENU = "AXShowMenu"

# Los roles que se pueden tocar aunque no declaren acciones.
ROLES_ACCIONABLES = frozenset({
    "AXButton", "AXPopUpButton", "AXMenuButton", "AXCheckBox",
    "AXRadioButton", "AXTextField", "AXTextArea", "AXSecureTextField",
    "AXComboBox", "AXLink", "AXMenuItem", "AXMenuBarItem", "AXSlider",
    "AXIncrementor", "AXRow", "AXCell", "AXDisclosureTriangle",
    "AXToolbarButton",
})

# Igual que en Windows: un árbol demasiado pequeño no se da por bueno a la
# primera. Aquí la causa habitual no es Chromium sino una app que aún está
# construyendo su ventana.
MINIMO_CREIBLE = 30
ESPERA_DESPERTAR = 0.3
INTENTOS_DESPERTAR = 2

# Hasta dónde se baja. AX no tiene el equivalente del CacheRequest de UIA para
# subárboles enteros, así que el recorrido va nivel a nivel y una jerarquía
# patológica podría no terminar nunca.
MAX_PROFUNDIDAD = 60


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
    return valor


def _varios(elemento, atributos) -> dict:
    """Varios atributos en una llamada, que es lo que hace esto viable.

    Es el equivalente del `CacheRequest` de UIA: sin él habría un salto entre
    procesos por atributo y por elemento, y en Windows eso medía 3 segundos
    por ventana.
    """
    servicios, _ = _api()
    error, valores = servicios.AXUIElementCopyMultipleAttributeValues(
        elemento, atributos, 0, None
    )
    if error != 0 or valores is None:
        return {}
    salida = {}
    for nombre, valor in zip(atributos, valores):
        # Los atributos que el elemento no tiene vuelven como un marcador de
        # error, no como None: hay que descartarlos o acaban en el árbol como
        # texto absurdo.
        if valor is None or type(valor).__name__ == "AXValueError":
            continue
        salida[nombre] = valor
    return salida


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


def _estado(datos) -> frozenset[str]:
    estados = set()
    if datos.get(HABILITADO) is False:
        estados.add("desactivado")
    if datos.get(CON_FOCO) is True:
        estados.add("con foco")
    if datos.get(SELECCIONADO) is True:
        estados.add("seleccionado")
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


def _convertir(elemento, camino: tuple, profundidad: int = 0) -> Nodo:
    datos = _varios(elemento, ATRIBUTOS)
    rol_ax = _texto(datos, ROL) or "AXUnknown"

    hijos = []
    if profundidad < MAX_PROFUNDIDAD:
        crios = _valor(elemento, HIJOS) or []
        for indice, hijo in enumerate(crios):
            try:
                hijos.append(_convertir(hijo, camino + (indice,), profundidad + 1))
            except Exception:
                # Un elemento que muere a mitad no se lleva a sus hermanos.
                continue

    return Nodo(
        rol=ui_tree.rol_ax(rol_ax),
        nombre=_texto(datos, TITULO, DESCRIPCION),
        valor=_valor_texto(datos),
        estado=_estado(datos),
        rect=_punto_y_tamano(datos),
        accionable=rol_ax in ROLES_ACCIONABLES,
        hijos=tuple(hijos),
        nativo=elemento,
        # AX no tiene nada como el RuntimeId de UIA, así que la identidad es
        # dónde estaba: el proceso y la ruta de índices desde la ventana.
        identidad=camino,
    )


# ---------- Ventanas ----------

def _apps():
    servicios, appkit = _api()
    activas = appkit.NSWorkspace.sharedWorkspace().runningApplications()
    for app in activas:
        # 0 es NSApplicationActivationPolicyRegular: las que salen en el Dock.
        if app.activationPolicy() != 0:
            continue
        yield app, servicios.AXUIElementCreateApplication(app.processIdentifier())


def ventanas() -> list[tuple[str, object, bool, int]]:
    """`(titulo, elemento, minimizada, pid)` de cada ventana abierta."""
    _exigir_permiso()
    salida = []
    for app, referencia in _apps():
        try:
            suyas = _valor(referencia, VENTANAS) or []
        except Exception:
            continue
        for ventana in suyas:
            titulo = _texto(_varios(ventana, (TITULO,)), TITULO)
            if not titulo.strip():
                titulo = str(app.localizedName() or "")
            if not titulo.strip():
                continue
            salida.append((
                titulo,
                ventana,
                bool(_valor(ventana, MINIMIZADA)),
                int(app.processIdentifier()),
            ))
    return salida


def _app_en_primer_plano() -> int:
    _, appkit = _api()
    frontal = appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return int(frontal.processIdentifier()) if frontal else 0


def _despertar(ventana, pid: int) -> Nodo:
    arbol = _convertir(ventana, (pid,))
    for _ in range(INTENTOS_DESPERTAR):
        if ui_tree.contar(arbol) >= MINIMO_CREIBLE:
            break
        time.sleep(ESPERA_DESPERTAR)
        arbol = _convertir(ventana, (pid,))
    return arbol


def capturar(
    titulo: str | None = None,
) -> tuple[Nodo, Rect, str, tuple[str, ...], str | None]:
    """El árbol crudo de una ventana, con su rectángulo y sus vecinas."""
    abiertas = ventanas()
    if not abiertas:
        raise ErrorUI("No hay ninguna ventana abierta con título")

    objetivo = None
    if titulo and titulo.strip():
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
    else:
        delante = _app_en_primer_plano()
        objetivo = next(
            (v for v in abiertas if v[3] == delante and not v[2]), abiertas[0]
        )

    nombre, elemento, minimizada, pid = objetivo

    aviso = None
    if minimizada:
        aviso = (
            f"Aviso: «{nombre}» está en el Dock, así que no se ve nada de "
            "ella. Restáurala para poder mirarla."
        )
    elif pid != _app_en_primer_plano():
        aviso = (
            f"Aviso: «{nombre}» no está delante, así que puede aparecer "
            "incompleta. Ponla en primer plano para verla entera."
        )

    try:
        arbol = _despertar(elemento, pid)
    except Exception as error:
        raise ErrorUI(
            f"No se pudo leer el árbol de «{nombre}»: {type(error).__name__}. "
            "Míralo con una captura."
        ) from error

    otras = tuple(v[0] for v in abiertas if v[0] != nombre)[:8]
    return arbol, arbol.rect, nombre, otras, aviso


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


def enfocar(elemento) -> None:
    servicios, _ = _api()
    error = servicios.AXUIElementSetAttributeValue(elemento, CON_FOCO, True)
    if error != 0:
        raise ErrorUI(f"No se pudo enfocar (error {error})")


def clic(elemento, boton: str = "left", veces: int = 1) -> str:
    """Pulsa, prefiriendo la acción del sistema al ratón."""
    if boton == "right":
        if _acepta(elemento, ACCION_MENU):
            _hacer(elemento, ACCION_MENU)
            return "acción menú"
    elif veces == 1 and _acepta(elemento, ACCION_PULSAR):
        _hacer(elemento, ACCION_PULSAR)
        return "acción pulsar"

    punto = _centro(elemento)
    if punto is None:
        raise ErrorUI(
            "Este elemento no admite ninguna acción y no tiene sitio en "
            "pantalla donde pinchar"
        )
    computer.clic_escritorio(punto[0], punto[1], boton=boton, veces=veces)
    return "ratón"


def escribir(elemento, texto: str) -> str:
    servicios, _ = _api()
    error = servicios.AXUIElementSetAttributeValue(elemento, VALOR, texto)
    if error == 0:
        return "atributo valor"
    enfocar(elemento)
    computer.teclear(texto)
    return "teclado"


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

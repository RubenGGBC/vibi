"""La GUI de esta máquina como texto, sin saber de qué sistema operativo es.

`screen.py` enseña la pantalla en píxeles y el modelo adivina coordenadas
sobre un JPEG reescalado. Esto es la otra forma de mirar: el árbol de
accesibilidad que las aplicaciones ya publican para los lectores de pantalla,
donde un botón dice que es un botón y trae su nombre escrito.

Aquí no hay una sola línea de Windows ni de macOS. Los backends
(`ui_windows`, `ui_macos`) traducen su árbol nativo a los `Nodo` de este
módulo, y a partir de ahí todo —podar, colapsar, numerar, dibujar y buscar—
es el mismo código para las dos plataformas. Es el reparto de `screen.py`
llevado más lejos: allí la geometría la sabía cada sistema y el criterio era
común; aquí lo único que sabe cada sistema es recorrer y actuar.

**Podar no es una optimización, es la función principal.** Medido el
2026-08-13 en este equipo: VS Code publica 2.468 nodos y solo 263 son cosas
que se ven y se pueden tocar; el resto son contenedores anónimos que UIA pone
de tres en tres. Sin la poda, un vistazo cuesta decenas de miles de tokens y
el modelo lee sobre todo estructura vacía.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace

# Cuántos nodos llegan al modelo como mucho. Medido contra las apps abiertas
# de este equipo: podados, VS Code deja 263, qBittorrent 323 y Steam 278. Con
# 400 caben enteras y el colapso queda para lo excepcional, que es justo lo
# que se quería: colapsar es perder información.
MAX_NODOS = 400

# Y cuántos hijos directos conserva un nodo antes de quedarse con una muestra.
# Una tabla de 4.000 celdas no se entiende mejor por mandarlas todas.
MAX_HIJOS = 40

# De los hijos que superan el tope, cuántos se conservan como muestra. Ver
# unos cuantos dice qué tipo de cosa hay dentro; verlos todos solo cuesta.
MUESTRA_HIJOS = 20

# Cuánto texto se lleva un solo elemento. El editor del Bloc de notas publica
# como «valor» el documento entero: sin tope, abrir un archivo de dos mil
# líneas mete dos mil líneas en el contexto por el hecho de mirar la ventana.
# Con esto se ve de qué va y, si hace falta el texto completo, se lee el
# archivo, que para eso está el disco.
MAX_VALOR = 200


# ---------- Geometría ----------

@dataclass(frozen=True)
class Rect:
    izquierda: int
    arriba: int
    derecha: int
    abajo: int

    @property
    def vacio(self) -> bool:
        return self.derecha <= self.izquierda or self.abajo <= self.arriba

    def solapa(self, otro: "Rect") -> bool:
        return (
            self.derecha > otro.izquierda
            and self.izquierda < otro.derecha
            and self.abajo > otro.arriba
            and self.arriba < otro.abajo
        )


RECT_NULO = Rect(0, 0, 0, 0)


# ---------- El árbol ----------

@dataclass(frozen=True)
class Huella:
    """Con qué se comprueba que un `ref` sigue señalando lo mismo.

    Un puntero nativo puede seguir vivo y apuntar a otra cosa: los controles
    se reciclan cuando una lista se repinta. Por eso la identidad se compara
    también por rol y nombre, y no solo por el identificador del sistema.
    """
    rol: str
    nombre: str
    identidad: tuple = ()


@dataclass(frozen=True)
class Nodo:
    rol: str
    nombre: str = ""
    valor: str | None = None
    estado: frozenset[str] = frozenset()
    rect: Rect = RECT_NULO
    accionable: bool = False
    hijos: tuple["Nodo", ...] = ()
    # Cuántos descendientes se han escondido en este punto al colapsar.
    ocultos: int = 0
    # El elemento del sistema. Opaco aquí: solo lo entiende su backend.
    nativo: object = None
    identidad: tuple = ()
    ref: str | None = None

    @property
    def huella(self) -> Huella:
        return Huella(self.rol, self.nombre, self.identidad)


@dataclass
class Snapshot:
    ventana: str
    otras_ventanas: tuple[str, ...]
    raiz: Nodo | None
    totales: int = 0
    omitidos: int = 0
    aviso: str | None = None
    # El identificador de la ventana en el sistema, para poder preguntar
    # después si sigue siendo la que tiene el foco. El título no vale para
    # esto: Spotify se retitula con la canción y Discord con el canal, así que
    # comparar títulos daba «no hay ninguna ventana que se llame X» sobre una
    # ventana que estaba ahí delante. Cero significa «este backend no sabe
    # decirlo», y entonces no se decide nada por él.
    handle: int = 0


def texto_cuadra(escrito: str, pedido: str) -> bool:
    """¿Un campo se ha quedado con lo que le pedimos?

    Laxo por arriba y estricto por abajo. Laxo porque un campo con máscara
    reformatea lo que le metes —un teléfono, una fecha— y un editor rico
    devuelve los espacios a su manera: exigir igualdad exacta daría falsos
    fallos. Estricto porque lo que se persigue es distinguir «ha entrado» de
    «no ha entrado nada», y ahí el caso que importa es el campo que se queda
    vacío o con un mísero salto de línea, como hace WhatsApp.

    El `in` a secas no vale: la cadena vacía está contenida en cualquier texto,
    así que un campo vacío pasaba por bueno. De ahí el corte de abajo.
    """
    a = " ".join((escrito or "").split())
    b = " ".join((pedido or "").split())
    if not b:
        return True
    if not a:
        return False
    return b in a or a in b


# ---------- Roles ----------

# Los nombres que ve el modelo. En español y los mismos en las dos
# plataformas: si Windows dijera «button» y macOS «AXButton», el mismo prompt
# tendría que funcionar con dos vocabularios y no funcionaría con ninguno.
ROLES_UIA = {
    50000: "botón",
    50001: "calendario",
    50002: "casilla",
    50003: "desplegable",
    50004: "campo",
    50005: "enlace",
    50006: "imagen",
    50007: "elemento",
    50008: "lista",
    50009: "menú",
    50010: "barra de menús",
    50011: "opción",
    50012: "progreso",
    50013: "opción",
    50014: "barra de desplazamiento",
    50015: "deslizador",
    50016: "selector",
    50017: "barra de estado",
    50018: "pestañas",
    50019: "pestaña",
    50020: "texto",
    50021: "barra de herramientas",
    50022: "ayuda",
    50023: "árbol",
    50024: "rama",
    50025: "elemento",
    50026: "grupo",
    50027: "tirador",
    50028: "tabla",
    50029: "celda",
    50030: "documento",
    50031: "botón",
    50032: "ventana",
    50033: "panel",
    50034: "encabezado",
    50035: "columna",
    50036: "tabla",
    50037: "título",
    50038: "separador",
    50039: "zoom",
    50040: "barra",
}

ROLES_AX = {
    "AXButton": "botón",
    "AXPopUpButton": "desplegable",
    "AXMenuButton": "botón",
    "AXCheckBox": "casilla",
    "AXRadioButton": "opción",
    "AXTextField": "campo",
    "AXTextArea": "campo",
    "AXSecureTextField": "campo",
    "AXComboBox": "desplegable",
    "AXLink": "enlace",
    "AXImage": "imagen",
    "AXList": "lista",
    "AXRow": "fila",
    "AXCell": "celda",
    "AXColumn": "columna",
    "AXMenu": "menú",
    "AXMenuBar": "barra de menús",
    "AXMenuItem": "opción",
    "AXMenuBarItem": "menú",
    "AXProgressIndicator": "progreso",
    "AXScrollBar": "barra de desplazamiento",
    "AXScrollArea": "panel",
    "AXSlider": "deslizador",
    "AXIncrementor": "selector",
    "AXTabGroup": "pestañas",
    "AXRadioGroup": "grupo",
    "AXStaticText": "texto",
    "AXToolbar": "barra de herramientas",
    "AXOutline": "árbol",
    "AXDisclosureTriangle": "rama",
    "AXGroup": "grupo",
    "AXTable": "tabla",
    "AXWindow": "ventana",
    "AXSheet": "ventana",
    "AXDrawer": "panel",
    "AXSplitGroup": "panel",
    "AXToolbarButton": "botón",
    "AXWebArea": "documento",
    "AXHeading": "encabezado",
    "AXSplitter": "separador",
    "AXValueIndicator": "indicador",
    "AXUnknown": "elemento",
}

# Lo que se puede pulsar, escribir o elegir. Un `ref` solo se gasta en esto
# (y en lo que se haya colapsado, para poder pedirlo).
ACCIONABLES = frozenset({
    "botón", "casilla", "desplegable", "campo", "enlace", "elemento",
    "opción", "menú", "deslizador", "selector", "pestaña", "rama",
    "celda", "fila", "columna", "calendario",
})

# Adornos: se van tengan nombre o no. Nada de lo que hay aquí se puede tocar
# ni dice nada que el modelo necesite, y un separador que se llame «separador»
# sigue sin aportar.
#
# Los contenedores —panel, grupo— no están en esta lista a propósito: se
# disuelven cuando vienen sin nombre, que es el caso de los tres `Pane`
# anónimos de UIA, y se quedan cuando lo traen, porque «Barra lateral» o
# «Guardar como» le dicen al modelo dónde está parado. Esa distinción también
# es la que permite acotar una búsqueda con `dentro_de`.
ADORNOS = frozenset({
    "separador", "tirador", "zoom", "barra de desplazamiento",
    "progreso", "indicador", "ayuda", "título",
})


def rol_uia(control_type: int) -> str:
    return ROLES_UIA.get(control_type, "elemento")


def rol_ax(role: str) -> str:
    return ROLES_AX.get(role, "elemento")


# ---------- Texto ----------

def recortar_valor(texto: str | None) -> str | None:
    """El valor de un elemento, acotado y en una línea.

    Los saltos de línea se aplanan porque el árbol usa la indentación para
    decir quién cuelga de quién: un valor multilínea rompe esa lectura y hace
    que un párrafo parezca la estructura de la ventana.
    """
    if not texto:
        return None
    plano = " ".join(texto.split())
    if len(plano) <= MAX_VALOR:
        return plano or None
    return plano[:MAX_VALOR] + f"… (+{len(plano) - MAX_VALOR} caracteres)"


def normalizar(texto: str) -> str:
    """Para comparar nombres sin que un acento decida el resultado.

    Lo que llega es lo que ha tecleado una persona hablando, o lo que ha
    escrito un modelo de memoria: «Guardar como» y «guardar COMO» tienen que
    encontrar el mismo menú. Mismo criterio que usa `screen.py` con los alias
    de las pantallas.
    """
    plano = unicodedata.normalize("NFKD", texto or "")
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return " ".join(plano.lower().split())


# ---------- Poda ----------

def _visible(nodo: Nodo, ventana: Rect) -> bool:
    if "oculto" in nodo.estado:
        return False
    if nodo.rect.vacio:
        return False
    if ventana.vacio:
        return True
    return nodo.rect.solapa(ventana)


def _aporta(nodo: Nodo) -> bool:
    if nodo.accionable or nodo.rol in ACCIONABLES:
        return True
    if nodo.rol in ADORNOS:
        return False
    return bool(nodo.nombre.strip() or (nodo.valor or "").strip())


def _redundante(hijo: Nodo, padre: Nodo) -> bool:
    """Si el hijo no dice nada que no dijera ya su padre.

    Los controles compuestos suelen colgar una etiqueta de texto con el mismo
    contenido que el nombre del control: cada pestaña del Bloc de notas
    duplicaba su título, y eran ocho líneas de cuarenta y seis. La etiqueta no
    se puede pulsar ni aporta nada que no estuviera una línea más arriba.
    """
    if hijo.hijos or hijo.accionable or hijo.rol in ACCIONABLES:
        return False
    if hijo.rol != "texto" or (hijo.valor or "").strip():
        return False
    suyo = normalizar(hijo.nombre)
    return bool(suyo) and suyo in normalizar(padre.nombre)


def sin_hermanos_repetidos(hijos: tuple[Nodo, ...]) -> tuple[Nodo, ...]:
    """Quita los hermanos que son el mismo elemento enumerado dos veces.

    No es una heurística de parecido: se comparan **identidades**, el runtime
    id que asigna el sistema. Dos nodos con la misma identidad no se parecen,
    **son el mismo**, y tenerlo dos veces en la lista de hijos es un fallo del
    que enumera, no información.

    Medido en WhatsApp Desktop el 20/08/2026: publica su panel principal dos
    veces con identidad `(42, 68252)` en ambos, y con él los 71 nodos que
    cuelgan — la mitad del árbol. El coste no era el tamaño sino la
    ambigüedad: 47 de 53 nombres aparecían repetidos, así que buscar «el campo
    de escribir el mensaje» daba siempre dos candidatos idénticos y el lote se
    paraba a preguntar cuál, sin que hubiera respuesta posible.

    Un nodo sin identidad nunca se descarta: no poder distinguirlos no es lo
    mismo que saber que son el mismo, y perder un control real es mucho peor
    que enseñar uno de más.
    """
    vistas: set[tuple] = set()
    salida = []
    for hijo in hijos:
        if hijo.identidad:
            if hijo.identidad in vistas:
                continue
            vistas.add(hijo.identidad)
        salida.append(hijo)
    return tuple(salida)


def podar(nodo: Nodo, ventana: Rect) -> list[Nodo]:
    """Deja lo que se ve y aporta; el resto se disuelve y sus hijos suben.

    Devuelve una lista y no un nodo porque un contenedor que no aporta nada no
    se sustituye por otra cosa: **desaparece y sus hijos ocupan su sitio**. Es
    lo que convierte los tres `Pane` anónimos que envuelven cada control en
    nada, sin perder el control de dentro.

    Un nodo invisible tampoco se lleva a sus hijos por delante: se vuelve
    transparente. Hay contenedores con rectángulo vacío cuyo contenido sí se
    ve, y descartarlos enteros costaba ventanas completas.
    """
    hijos = sin_hermanos_repetidos(
        tuple(h for hijo in nodo.hijos for h in podar(hijo, ventana))
    )
    if not _visible(nodo, ventana):
        return list(hijos)
    if _aporta(nodo):
        hijos = tuple(h for h in hijos if not _redundante(h, nodo))
        return [replace(nodo, hijos=hijos)]
    return list(hijos)


def contar(nodo: Nodo) -> int:
    return 1 + sum(contar(hijo) for hijo in nodo.hijos)


# ---------- Colapso ----------

def _colapsar_hermanos(nodo: Nodo, max_hijos: int, muestra: int) -> Nodo:
    hijos = tuple(_colapsar_hermanos(h, max_hijos, muestra) for h in nodo.hijos)
    if len(hijos) <= max_hijos:
        return replace(nodo, hijos=hijos)
    conservados = hijos[:muestra]
    escondidos = sum(contar(h) for h in hijos[muestra:])
    return replace(
        nodo,
        hijos=conservados,
        ocultos=nodo.ocultos + escondidos,
    )


def _mas_gordo(nodo: Nodo) -> tuple[int, Nodo | None]:
    """El descendiente con más nodos dentro, para colapsarlo antes que otro."""
    mejor_peso, mejor = 0, None
    for hijo in nodo.hijos:
        peso = contar(hijo)
        if peso > mejor_peso and hijo.hijos:
            mejor_peso, mejor = peso, hijo
        peso_nieto, nieto = _mas_gordo(hijo)
        if peso_nieto > mejor_peso:
            mejor_peso, mejor = peso_nieto, nieto
    return mejor_peso, mejor


def _colapsar_nodo(raiz: Nodo, objetivo: Nodo) -> Nodo:
    if raiz is objetivo:
        escondidos = sum(contar(h) for h in raiz.hijos)
        return replace(raiz, hijos=(), ocultos=raiz.ocultos + escondidos)
    return replace(
        raiz, hijos=tuple(_colapsar_nodo(h, objetivo) for h in raiz.hijos)
    )


def colapsar(
    raiz: Nodo, max_nodos: int = MAX_NODOS, max_hijos: int = MAX_HIJOS
) -> Nodo:
    """Recorta hasta caber, empezando por lo más gordo y contando lo que tapa.

    Nunca se esconde nada en silencio: lo que se va queda contado en `ocultos`
    del nodo que lo tapaba, y de ahí sale la línea que el modelo lee para
    saber que hay más y con qué `ref` pedirlo.
    """
    actual = _colapsar_hermanos(raiz, max_hijos, MUESTRA_HIJOS)
    # Colapsar el subárbol más grande, repetidamente, hasta caber. Termina
    # siempre: cada vuelta quita al menos un nodo, o no queda nada que quitar.
    while contar(actual) > max_nodos:
        _, gordo = _mas_gordo(actual)
        if gordo is None:
            break
        actual = _colapsar_nodo(actual, gordo)
    return actual


# ---------- Referencias ----------

class Registro:
    """Los `ref` del último snapshot y a qué elemento apunta cada uno.

    Una sola generación: cada snapshot borra el anterior. Se pensó guardar dos
    para tolerar que el modelo mezclara refs viejos con nuevos, y es
    exactamente lo que no se quiere: un `ref` que sobrevive a la foto en la que
    salió es un clic sobre algo que ya no está donde se creía. Vale más un
    error claro que diga que hay que volver a mirar.
    """

    def __init__(self) -> None:
        self._por_ref: dict[str, tuple[object, Huella]] = {}

    def limpiar(self) -> None:
        self._por_ref.clear()

    def guardar(self, ref: str, nativo: object, huella: Huella) -> None:
        self._por_ref[ref] = (nativo, huella)

    def obtener(self, ref: str) -> tuple[object, Huella] | None:
        return self._por_ref.get(ref)

    def __contains__(self, ref: object) -> bool:
        return ref in self._por_ref

    def __len__(self) -> int:
        return len(self._por_ref)


def _merece_ref(nodo: Nodo) -> bool:
    if nodo.accionable or nodo.rol in ACCIONABLES:
        return True
    # Lo colapsado, aunque no se pueda pulsar: su `ref` es con lo que se pide
    # lo que hay debajo.
    if nodo.ocultos > 0:
        return True
    # Y los contenedores con nombre, que son los ámbitos de `dentro_de`. Sin
    # esto no hay forma de decir «el Aceptar de este diálogo», que es
    # justamente lo que desambigua cuando hay tres botones «Aceptar».
    return bool(nodo.nombre.strip() and nodo.hijos)


def asignar_refs(raiz: Nodo, registro: Registro) -> Nodo:
    """Numera en orden de lectura lo que se puede tocar, pedir o acotar.

    La raíz se queda sin `ref`: es la ventana, no se pinta en el árbol porque
    ya está en la cabecera, y numerar algo que no sale hace que la cuenta
    empiece en `e2` sin que nada lo explique.
    """
    registro.limpiar()
    contador = 0

    def recorrer(nodo: Nodo, es_raiz: bool = False) -> Nodo:
        nonlocal contador
        ref = None
        if not es_raiz and _merece_ref(nodo):
            contador += 1
            ref = f"e{contador}"
            registro.guardar(ref, nodo.nativo, nodo.huella)
        return replace(
            nodo, ref=ref, hijos=tuple(recorrer(h) for h in nodo.hijos)
        )

    return recorrer(raiz, es_raiz=True)


# ---------- Búsqueda ----------

def recorrer_todos(nodo: Nodo):
    yield nodo
    for hijo in nodo.hijos:
        yield from recorrer_todos(hijo)


def por_ref(raiz: Nodo, ref: str) -> Nodo | None:
    for nodo in recorrer_todos(raiz):
        if nodo.ref == ref:
            return nodo
    return None


def buscar(
    raiz: Nodo,
    rol: str | None = None,
    nombre: str | None = None,
    dentro_de: str | None = None,
) -> list[Nodo]:
    """Los candidatos que casan con la descripción, sin elegir por nadie.

    Devuelve la lista entera a propósito. Quedarse con el primero cuando hay
    tres «Aceptar» es exactamente cómo se pulsa el que no era, y quien llama
    tiene que poder parar y preguntar.

    El nombre se compara primero exacto y solo después por contenido, para que
    «Guardar» no gane a «Guardar como» cuando se pidió «Guardar».
    """
    ambito = raiz
    if dentro_de:
        ambito = por_ref(raiz, dentro_de)
        if ambito is None:
            return []

    candidatos = list(recorrer_todos(ambito))
    if dentro_de:
        candidatos = candidatos[1:]

    if rol:
        objetivo = normalizar(rol)
        candidatos = [n for n in candidatos if normalizar(n.rol) == objetivo]

    if not nombre:
        return candidatos

    buscado = normalizar(nombre)
    exactos = [n for n in candidatos if normalizar(n.nombre) == buscado]
    if exactos:
        return exactos
    return [n for n in candidatos if buscado in normalizar(n.nombre)]


# ---------- Render ----------

def _linea(nodo: Nodo, nivel: int) -> str:
    marca = f"[{nodo.ref}]" if nodo.ref else "    "
    partes = [f'{marca} {"  " * nivel}{nodo.rol}']
    if nodo.nombre.strip():
        partes.append(f'"{nodo.nombre.strip()}"')
    if (nodo.valor or "").strip():
        partes.append(f'= "{nodo.valor.strip()}"')
    if nodo.estado:
        partes.append(f'({", ".join(sorted(nodo.estado))})')
    if nodo.ocultos:
        pedir = f", pide {nodo.ref}" if nodo.ref else ""
        partes.append(f"(+{nodo.ocultos} dentro{pedir})")
    return " ".join(partes)


def render(snapshot: Snapshot) -> str:
    """El árbol tal como lo lee el modelo.

    Texto indentado y no JSON: medido sobre el mismo árbol, 2.733 caracteres
    contra 5.235 del JSON minificado. Y el snapshot no se paga una vez, se
    arrastra en el contexto de todos los turnos siguientes.

    La última línea, la de la cuenta, no es decorativa: es lo que impide que
    el modelo dé por visto todo lo que hay cuando se ha podado la mitad.
    """
    lineas = [f'ventana con foco: "{snapshot.ventana}"']
    if snapshot.otras_ventanas:
        lineas.append("otras ventanas: " + ", ".join(snapshot.otras_ventanas))
    if snapshot.aviso:
        lineas.append(snapshot.aviso)
    lineas.append("")

    if snapshot.raiz is None:
        lineas.append(
            "Esta aplicación no publica árbol de accesibilidad. Mírala con "
            "devices_screenshot y actúa por coordenadas."
        )
        return "\n".join(lineas)

    def recorrer(nodo: Nodo, nivel: int) -> None:
        lineas.append(_linea(nodo, nivel))
        for hijo in nodo.hijos:
            recorrer(hijo, nivel + 1)

    # La raíz es la ventana y ya está en la cabecera: se entra por sus hijos.
    for hijo in snapshot.raiz.hijos:
        recorrer(hijo, 0)

    lineas.append("")
    resumen = f"{snapshot.totales} nodos"
    if snapshot.omitidos:
        resumen += (
            f" · {snapshot.omitidos} omitidos "
            "(fuera de pantalla o decorativos)"
        )
    lineas.append(resumen)
    return "\n".join(lineas)

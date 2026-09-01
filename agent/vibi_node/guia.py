"""Señalar en vez de tocar.

`ui.py` mira una ventana y actúa sobre ella. Esto es la tercera cosa que sabe
hacer alguien sentado a tu lado y que hasta ahora Vibi no: **poner el dedo
encima**. Devuelve una foto de tu pantalla y, aparte, los rectángulos de los
elementos de los que se está hablando. Quien pulsa eres tú.

**Las marcas no salen de mirar la foto, salen del árbol.** El sistema ya
publica el rectángulo exacto de cada botón para los lectores de pantalla, y la
captura ya devuelve el mapa que traduce escritorio a imagen. Con las dos cosas,
señalar es una multiplicación: la caja cae donde cae el botón, con la precisión
del sistema operativo y no con la del ojo de un modelo sobre un JPEG reducido.

Y por eso **el modelo no mira la imagen**. Ya sabe lo que hay en la ventana,
porque lo leyó en el árbol; para señalar sólo dice cuáles. La foto viaja hacia
la persona y nunca hacia el contexto: una guía cuesta una captura y cero tokens
de imagen.

**Aquí no se espera a nada.** Un lote puede apuntar a la opción de un menú que
abrirá el paso anterior, porque el lote va a abrirlo. Una guía sólo puede
marcar lo que se ve ahora, porque la foto es de ahora: lo que todavía no
existe se enseña en la guía siguiente, cuando la persona haya abierto el menú.
"""
from __future__ import annotations

from . import screen, ui, ui_tree
from .ui_tree import Nodo, Rect, Snapshot

# Cuántas marcas caben en una guía. Más de esto deja de ser una indicación y
# pasa a ser un plano: el tope obliga a que cada guía diga una cosa, y a que un
# camino largo se cuente en varias con la persona avanzando entre medias, que
# es como se enseña algo a alguien de verdad.
MAX_MARCAS = 6

# Lo que se le da de aire a cada marca, en píxeles de la imagen. Un recuadro
# pegado al borde del botón tapa justo lo que hay que leer.
HOLGURA = 3

# Lo que puede escribirse al lado de un número en la leyenda. Es una etiqueta,
# no la explicación: la explicación la escribe Vibi en el mensaje.
MAX_TEXTO = 80


def _descriptores(objetivos: object) -> list[dict]:
    """Lo que ha pedido el modelo, validado antes de tocar la pantalla.

    Se valida entero primero y no sobre la marcha porque lo caro es la foto:
    descubrir en el objetivo cuarto que faltaba un campo, después de haber
    fotografiado, es pagar la captura para nada.
    """
    if not isinstance(objetivos, (list, tuple)) or not objetivos:
        raise ui.ErrorUI(
            "sin_objetivos",
            "Una guía necesita al menos un objetivo: qué hay que señalar.",
        )
    if len(objetivos) > MAX_MARCAS:
        raise ui.ErrorUI(
            "demasiadas_marcas",
            f"Una guía señala {MAX_MARCAS} cosas como mucho y me has pedido "
            f"{len(objetivos)}. Cuenta el camino en varias guías: enseña las "
            "primeras, deja que las haga y sigue desde donde quede.",
        )

    limpios: list[dict] = []
    for objetivo in objetivos:
        if not isinstance(objetivo, dict):
            raise ui.ErrorUI(
                "objetivo_invalido",
                "Cada objetivo es un objeto con `ref`, o con `rol` y `nombre`.",
            )
        ref = str(objetivo.get("ref") or "").strip()
        rol = str(objetivo.get("rol") or "").strip()
        nombre = str(objetivo.get("nombre") or "").strip()
        if not ref and not rol and not nombre:
            raise ui.ErrorUI(
                "descriptor_vacio",
                "Para señalar algo hace falta su `ref` de la última lectura, "
                "o al menos su rol o su nombre.",
            )
        limpios.append({
            "ref": ref,
            "rol": rol,
            "nombre": nombre,
            "dentro_de": str(objetivo.get("dentro_de") or "").strip(),
            "texto": str(objetivo.get("texto") or "").strip()[:MAX_TEXTO],
        })
    return limpios


def _resolver(
    snapshot: Snapshot, anterior: Snapshot | None, descriptor: dict
) -> Nodo:
    """El elemento del árbol vivo al que apunta un descriptor.

    El `ref` se busca en el árbol recién leído y se comprueba contra el de la
    lectura anterior: los `ref` se reparten en orden de lectura, así que en una
    ventana que no ha cambiado `e12` sigue siendo `e12`, y en una que sí ha
    cambiado puede haber pasado a nombrar otra cosa. Señalar esa otra cosa sería
    mandar a la persona a pulsar donde no era y dejarle creer que se equivocó
    ella.
    """
    raiz = snapshot.raiz
    if raiz is None:
        raise ui.ErrorUI(
            "sin_arbol",
            f'«{snapshot.ventana}» no publica nada que se pueda señalar. '
            "Esa aplicación no da accesibilidad: enséñala con una captura.",
        )

    ref = descriptor["ref"]
    if ref:
        nodo = ui_tree.por_ref(raiz, ref)
        if nodo is None:
            raise ui.ErrorUI(
                "ref_desconocido",
                f"No hay ningún «{ref}» en la ventana. Vuelve a mirarla y usa "
                "un ref de la última vez.",
            )
        previo = (
            ui_tree.por_ref(anterior.raiz, ref)
            if anterior is not None and anterior.raiz is not None
            else None
        )
        if previo is not None and previo.huella != nodo.huella:
            raise ui.ErrorUI(
                "ref_caducado",
                f"«{ref}» ya no señala lo mismo que cuando lo miraste "
                f"({previo.rol} «{previo.nombre}» era, y ahora es "
                f"{nodo.rol} «{nodo.nombre}»). La ventana ha cambiado: vuelve "
                "a mirarla.",
            )
        return nodo

    candidatos = ui_tree.buscar(
        raiz,
        rol=descriptor["rol"] or None,
        nombre=descriptor["nombre"] or None,
        dentro_de=descriptor["dentro_de"] or None,
    )
    if not candidatos:
        etiqueta = descriptor["nombre"] or descriptor["rol"]
        raise ui.ErrorUI(
            "no_encontrado",
            f'No veo nada que case con «{etiqueta}» en '
            f'«{snapshot.ventana}». Vuelve a mirar la ventana.',
        )
    if len(candidatos) > 1:
        # Igual que en un lote: tres «Aceptar» son una pregunta y no una
        # opción por defecto. Y aquí importa más, porque quien pulsa lo que se
        # le señale es una persona que se fía.
        raise ui.ErrorUI(
            "ambiguo",
            f"Hay {len(candidatos)} candidatos para {descriptor['nombre'] or descriptor['rol']}: "
            f"{ui._describir(candidatos)}. Acota con dentro_de o usa un ref.",
            {"candidatos": [c.ref for c in candidatos if c.ref]},
        )
    return candidatos[0]


def _pantalla_de(rect: Rect, pantallas: list[dict]) -> str:
    """El número del monitor donde cae un rectángulo, para pedir esa foto.

    Vacío significa «no sé»: entonces se captura la que tenga el ratón, que es
    lo que significa «mi pantalla» cuando hay dos y nadie ha dicho cuál.
    """
    centro_x = (rect.izquierda + rect.derecha) // 2
    centro_y = (rect.arriba + rect.abajo) // 2
    for pantalla in pantallas:
        if (
            pantalla["x"] <= centro_x < pantalla["x"] + pantalla["ancho"]
            and pantalla["y"] <= centro_y < pantalla["y"] + pantalla["alto"]
        ):
            return str(pantalla["numero"])
    return ""


def proyectar(rect: Rect, detalle: dict) -> dict | None:
    """De un rectángulo del escritorio al mismo rectángulo dentro de la foto.

    Es la cuenta de la que depende toda la feature, y la que hace fácil
    equivocarse con dos monitores: el de la izquierda vive en coordenadas
    negativas, así que hay que restar el origen **antes** de escalar.

    Devuelve `None` para lo que no se ve en esta foto —está en el otro monitor,
    o scrolleado fuera—: marcar eso sería dibujar un recuadro en un borde
    señalando a nada.
    """
    ancho_imagen = int(detalle.get("ancho") or 0)
    alto_imagen = int(detalle.get("alto") or 0)
    ancho_real = int(detalle.get("ancho_real") or 0) or ancho_imagen
    alto_real = int(detalle.get("alto_real") or 0) or alto_imagen
    if not (ancho_imagen and alto_imagen and ancho_real and alto_real):
        return None

    escala_x = ancho_imagen / ancho_real
    escala_y = alto_imagen / alto_real
    origen_x = int(detalle.get("origen_x") or 0)
    origen_y = int(detalle.get("origen_y") or 0)

    izquierda = (rect.izquierda - origen_x) * escala_x - HOLGURA
    arriba = (rect.arriba - origen_y) * escala_y - HOLGURA
    derecha = (rect.derecha - origen_x) * escala_x + HOLGURA
    abajo = (rect.abajo - origen_y) * escala_y + HOLGURA

    # Recortado a la foto: un elemento a medio salir se marca con la mitad que
    # se ve, que es la mitad que la persona puede pulsar.
    recortada = (
        izquierda < 0 or arriba < 0
        or derecha > ancho_imagen or abajo > alto_imagen
    )
    izquierda = max(0.0, min(izquierda, ancho_imagen))
    arriba = max(0.0, min(arriba, alto_imagen))
    derecha = max(0.0, min(derecha, ancho_imagen))
    abajo = max(0.0, min(abajo, alto_imagen))
    if derecha - izquierda < 1 or abajo - arriba < 1:
        return None

    return {
        "x": round(izquierda),
        "y": round(arriba),
        "ancho": round(derecha - izquierda),
        "alto": round(abajo - arriba),
        "recortada": recortada,
    }


def senalar(objetivos: object, ventana: str | None = None) -> dict:
    """Una foto de la pantalla y dónde está, dentro de ella, cada objetivo.

    Devuelve el JPEG aparte de las marcas a propósito: la imagen sube por HTTP
    hacia la persona y las marcas vuelven por el canal de órdenes, que es el
    reparto que ya hace `screen.capture` y por el mismo motivo —el canal
    descarta lo que pase de 200 KB—.
    """
    descriptores = _descriptores(objetivos)

    # El árbol de antes, para poder decir que un `ref` ha dejado de significar
    # lo que significaba. Se coge ahora porque `_mirar` lo sustituye.
    anterior = ui._ultimo
    snapshot = ui._mirar(ventana)
    nodos = [_resolver(snapshot, anterior, d) for d in descriptores]

    # Lo que no ocupa sitio no llega hasta aquí: `ui_tree.podar` ya descarta
    # los rectángulos vacíos, así que todo nodo del árbol tiene dónde marcarse.
    pantallas = screen.pantallas()
    capturada = screen.capturar(_pantalla_de(nodos[0].rect, pantallas))
    detalle = capturada["detalle"]

    marcas = []
    fuera = []
    for numero, (descriptor, nodo) in enumerate(zip(descriptores, nodos), 1):
        caja = proyectar(nodo.rect, detalle)
        if caja is None:
            fuera.append(descriptor["ref"] or descriptor["nombre"] or nodo.rol)
            continue
        marcas.append({
            "numero": numero,
            "ref": nodo.ref or "",
            "rol": nodo.rol,
            "nombre": nodo.nombre,
            "texto": descriptor["texto"],
            **caja,
        })

    if not marcas:
        raise ui.ErrorUI(
            "fuera_de_pantalla",
            "Nada de lo que quieres señalar se ve en esa pantalla. Comprueba "
            "que la ventana está delante y en el monitor que crees.",
        )

    return {
        "jpeg": capturada["jpeg"],
        "marcas": marcas,
        "detalle": {
            "ventana": snapshot.ventana,
            "pantalla": detalle.get("pantalla", ""),
            "ancho": detalle.get("ancho", 0),
            "alto": detalle.get("alto", 0),
            "bytes": len(capturada["jpeg"]),
            # Lo que se pidió y no se pudo marcar. Nunca en silencio: si la
            # persona espera tres números y ve dos, tiene que salir por qué.
            "fuera": fuera,
        },
    }

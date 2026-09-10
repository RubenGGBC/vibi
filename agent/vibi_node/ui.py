"""Mirar la GUI y actuar sobre ella, varias acciones de una vez.

Esta es la puerta: `capturar()` para ver y `ejecutar_lote()` para hacer. Elige
el backend de la plataforma, guarda el último árbol con sus `ref` y ejecuta
secuencias enteras sin volver a preguntarle al modelo.

**El lote existe por la latencia, y la latencia es la del modelo.** Guardar un
archivo con nombre son cuatro acciones —abrir el menú, elegir «Guardar como»,
escribir el nombre, aceptar— y por el camino de siempre son cuatro turnos, cada
uno con su captura para ver qué pasó. Aquí es una llamada: unos cientos de
milisegundos por paso contra varios segundos por turno.

**Lo que hace seguro ese optimismo es que cada paso se resuelve justo antes de
ejecutarse.** El árbol se vuelve a leer después de cada acción, así que un paso
puede apuntar a algo que todavía no existía cuando se compuso el lote —la
opción del menú que aún no se había abierto—, y un `ref` que ya no señala lo
mismo se detecta antes de pulsar nada. El lote para al primer fallo y devuelve
el estado real: nunca sigue a ciegas.
"""
from __future__ import annotations

import platform
import time

from . import ui_tree
from .ui_tree import Nodo, Registro, Snapshot

# Cuántos pasos admite un lote. Más que esto no es una secuencia, es un
# programa, y un programa que nadie mira acaba pulsando lo que no era.
MAX_PASOS = 20

# El tope de tiempo de un lote entero. Va por debajo de los 45 s que espera
# `nodes.dispatch`, así que un lote nunca provoca un timeout de nodo: cuando
# se agota, se devuelve lo hecho con su árbol y decide el modelo.
PRESUPUESTO = 30.0

# Lo que se espera tras una acción antes de volver a leer el árbol. Una
# ventana que acaba de recibir un clic está animando, y leerla a mitad da un
# árbol que no es ni el de antes ni el de después.
ESPERA_ASENTAR = 0.15

# Cuánto se insiste buscando algo que todavía no está.
ESPERA_BUSQUEDA = 1.5

# Las que no se pueden hacer sin decir sobre qué. `escribir` no está aquí a
# propósito: sin objetivo escribe donde esté el foco, que es lo que hace un
# teclado y lo que espera cualquiera que acabe de enfocar un campo.
ACCIONES_CON_OBJETIVO = frozenset({
    "clic", "seleccionar", "expandir", "contraer", "enfocar", "desplazar",
})
ACCIONES = frozenset({
    "clic", "escribir", "tecla", "seleccionar", "expandir", "contraer",
    "enfocar", "esperar", "snapshot", "activar", "desplazar",
})

# Cómo se dice «mueve esta lista». En español y como lo pide el modelo, que
# escribió «abajo» tal cual la vez que lo intentó.
DIRECCIONES = ("abajo", "arriba", "izquierda", "derecha")

# Lo que puede durar una pausa suelta. Más que esto no es esperar a que la
# ventana se asiente, es dormir dentro del lote.
MAX_PAUSA = 5.0


class ErrorUI(Exception):
    """Algo que impide seguir, con un código que el modelo puede entender."""

    def __init__(self, codigo: str, mensaje: str, datos: dict | None = None):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.datos = datos or {}


# ---------- El backend de esta máquina ----------

def _backend():
    sistema = platform.system()
    if sistema == "Windows":
        from . import ui_windows

        return ui_windows
    if sistema == "Darwin":
        from . import ui_macos

        return ui_macos
    raise ErrorUI(
        "sin_backend",
        f"Leer el árbol de accesibilidad no está hecho para {sistema}. "
        "Usa devices_screenshot y actúa por coordenadas.",
    )


def disponible() -> bool:
    try:
        return _backend().disponible()
    except Exception:
        return False


# ---------- El último árbol ----------

_registro = Registro()
_ultimo: Snapshot | None = None


def olvidar() -> None:
    """Tira el último árbol. Para las pruebas y para cuando cambia el nodo."""
    global _ultimo
    _registro.limpiar()
    _ultimo = None


def _preparar(
    crudo: Nodo,
    rect,
    titulo,
    otras,
    aviso,
    expandir=None,
    handle: int = 0,
    registro: Registro | None = None,
) -> Snapshot:
    """De árbol nativo a snapshot listo para leer: podar, colapsar, numerar.

    `registro` existe para poder numerar **sin** pisar el compartido. Lo usa la
    vigilancia, que mira una ventana cada pocos segundos por su cuenta: si
    numerara sobre `_registro`, le caducaría al modelo los `ref` de su último
    vistazo en mitad de un turno y el lote siguiente fallaría sin motivo
    aparente.
    """
    destino = _registro if registro is None else registro
    total_crudo = ui_tree.contar(crudo)
    podados = ui_tree.podar(crudo, rect)
    raiz = podados[0] if podados else None

    if raiz is not None and expandir:
        # Expandir es mirar de nuevo acotando el ámbito: se numera primero
        # para poder localizar el `ref` pedido, y se sigue desde ahí.
        numerado = ui_tree.asignar_refs(raiz, Registro())
        objetivo = ui_tree.por_ref(numerado, expandir)
        if objetivo is None:
            raise ErrorUI(
                "ref_desconocido",
                f"No hay ningún «{expandir}» en la ventana. Vuelve a mirarla "
                "y usa un ref de la última vez.",
            )
        raiz = objetivo

    if raiz is not None:
        raiz = ui_tree.colapsar(raiz)
        raiz = ui_tree.asignar_refs(raiz, destino)

    vistos = ui_tree.contar(raiz) if raiz is not None else 0
    return Snapshot(
        ventana=titulo,
        otras_ventanas=tuple(otras),
        raiz=raiz,
        totales=vistos,
        omitidos=max(0, total_crudo - vistos),
        aviso=aviso,
        handle=handle,
    )


def _mirar(
    ventana: str | None = None,
    expandir: str | None = None,
    handle: int = 0,
    registro: Registro | None = None,
) -> Snapshot:
    """Lee una ventana, por su identificador si se sabe y por su título si no.

    **Con `handle` no se vuelve a mirar el título**, y esa es toda la gracia:
    el título es lo que cambia —Spotify se retitula con la canción, Discord con
    el canal, un navegador con la pestaña— y el identificador no cambia
    mientras la ventana viva.
    """
    global _ultimo
    backend = _backend()
    try:
        if handle:
            try:
                leido = backend.capturar(ventana, handle=handle)
            except TypeError:
                # Un backend que aún no sabe de handles: se sigue por título,
                # que es como funcionaba antes de esto.
                leido = backend.capturar(ventana)
        else:
            leido = backend.capturar(ventana)
    except ErrorUI:
        raise
    except Exception as error:
        raise ErrorUI("sin_arbol", str(error)) from error
    # El handle es el sexto elemento y llegó después que el resto: un backend
    # que no lo dé sigue funcionando, solo que sin poder decidir sobre el foco.
    crudo, rect, titulo, otras, aviso = leido[:5]
    handle = int(leido[5]) if len(leido) > 5 else 0
    snapshot = _preparar(
        crudo, rect, titulo, otras, aviso, expandir, handle, registro
    )
    # Quien mira con registro propio —la vigilancia— tampoco toca el último
    # árbol: `_ultimo` es el del usuario, y lo que decide sobre el foco.
    if registro is None:
        _ultimo = snapshot
    return snapshot


def sello_de(ventana: str | None = None) -> dict:
    """Cómo está una ventana ahora, para comparar con cómo estaba antes.

    Es lo que usa la vigilancia, y por eso no toca nada compartido: numera
    sobre un registro de usar y tirar y no toca `_ultimo`. Si esto pisara el
    estado del turno, vigilar una ventana rompería la conversación que la está
    manejando, que es justo la mitad de los casos.
    """
    snapshot = _mirar(ventana, registro=Registro())
    return {
        "ventana": snapshot.ventana,
        "arbol": ui_tree.render(snapshot),
        "vacio": snapshot.raiz is None or snapshot.totales <= 1,
    }


def capturar(ventana: str | None = None, expandir: str | None = None) -> dict:
    """Lo que se ve ahora, en texto, con sus `ref` listos para usar."""
    inicio = time.monotonic()
    snapshot = _mirar(ventana, expandir)
    return {
        "arbol": ui_tree.render(snapshot),
        "ventana": snapshot.ventana,
        "nodos": snapshot.totales,
        "omitidos": snapshot.omitidos,
        "vacio": snapshot.raiz is None or snapshot.totales <= 1,
        "ms": round((time.monotonic() - inicio) * 1000),
    }


# ---------- Resolver el objetivo de un paso ----------

def _nativo_de(nodo: Nodo):
    if nodo.nativo is None:
        raise ErrorUI(
            "sin_elemento",
            "Ese elemento ya no existe en la ventana. Vuelve a mirarla.",
        )
    return nodo.nativo


def _por_ref(ref: str):
    entrada = _registro.obtener(ref)
    if entrada is None:
        raise ErrorUI(
            "ref_desconocido",
            f"No conozco ningún «{ref}». Los ref son los de la última vez "
            "que miraste: vuelve a mirar y usa los nuevos.",
        )
    nativo, huella = entrada
    if not _backend().sigue_vivo(nativo, huella):
        raise ErrorUI(
            "ref_caducado",
            f"«{ref}» ya no señala lo mismo que cuando lo miraste "
            f"({huella.rol} «{huella.nombre}»). La ventana ha cambiado.",
        )
    return nativo


def _describir(candidatos: list[Nodo]) -> str:
    partes = []
    for nodo in candidatos[:6]:
        etiqueta = f'{nodo.rol} "{nodo.nombre}"'
        if nodo.ref:
            etiqueta = f"{nodo.ref}: {etiqueta}"
        partes.append(etiqueta)
    if len(candidatos) > 6:
        partes.append(f"y {len(candidatos) - 6} más")
    return "; ".join(partes)


def _buscar_con_espera(
    descriptor: dict,
    snapshot: Snapshot,
    ventana: str | None,
    limite: float,
    handle: int = 0,
) -> tuple[Nodo, Snapshot]:
    """Busca, y si no está insiste releyendo hasta que se acabe el tiempo.

    Se relee el árbol entero en cada vuelta y no se consulta un caché: lo que
    se está esperando es justamente que la ventana cambie, y preguntarle a una
    foto vieja si ya ha cambiado no puede contestar que sí.
    """
    rol = descriptor.get("rol")
    nombre = descriptor.get("nombre")
    dentro_de = descriptor.get("dentro_de")
    if not (rol or nombre):
        raise ErrorUI(
            "descriptor_vacio",
            "Para buscar algo hace falta al menos su rol o su nombre.",
        )

    fin = time.monotonic() + min(ESPERA_BUSQUEDA, max(0.0, limite))
    actual = snapshot
    while True:
        if actual.raiz is not None:
            candidatos = ui_tree.buscar(
                actual.raiz, rol=rol, nombre=nombre, dentro_de=dentro_de
            )
            if len(candidatos) == 1:
                return candidatos[0], actual
            if len(candidatos) > 1:
                # No se elige por nadie: tres «Aceptar» son una pregunta, no
                # una opción por defecto.
                raise ErrorUI(
                    "ambiguo",
                    f"Hay {len(candidatos)} candidatos para "
                    f"{descriptor}: {_describir(candidatos)}. "
                    "Acota con dentro_de o usa un ref.",
                    {"candidatos": [c.ref for c in candidatos if c.ref]},
                )
        if time.monotonic() >= fin:
            raise ErrorUI(
                "no_encontrado",
                f"No hay nada que case con {descriptor} en "
                f'«{actual.ventana}».',
            )
        actual = _mirar(ventana, handle=handle)


# ---------- Ejecutar un paso ----------

def _texto_de(paso: dict, clave: str) -> str:
    valor = paso.get(clave)
    if valor is None or str(valor) == "":
        raise ErrorUI(
            "falta_dato", f"Al paso «{paso.get('accion')}» le falta «{clave}»."
        )
    return str(valor)


def entrada_global_llega(snapshot: Snapshot) -> bool:
    """¿El teclado y el ratón van a caer en la ventana que estamos mirando?

    Esta es la pregunta que faltaba. El árbol se lee de cualquier ventana, esté
    donde esté —y eso está bien, es la gracia de UIA—, pero el teclado y el
    ratón no eligen destino: van a la que tenga el foco. Leer de una y escribir
    en otra es lo que acabó tecleando un mensaje de WhatsApp sobre un vídeo de
    YouTube.

    Devuelve `True` cuando no se puede saber, a propósito: un backend que no
    publique `handle_en_primer_plano` no debe quedarse sin poder teclear por
    una comprobación que no sabe hacer. Las dos plataformas la publican desde
    el 2026-09-09; hasta ese día macOS no, y por eso allí esta comprobación
    decía que sí a todo y la entrada global se iba a la ventana de delante
    fuera cual fuera la que se estaba mirando.
    """
    if not snapshot.handle:
        return True
    delante = getattr(_backend(), "handle_en_primer_plano", None)
    if delante is None:
        return True
    try:
        actual = int(delante())
    except Exception:
        return True
    if not actual:
        return True
    return actual == snapshot.handle


def _exigir_primer_plano(snapshot: Snapshot, que: str) -> None:
    if entrada_global_llega(snapshot):
        return
    raise ErrorUI(
        "ventana_de_fondo",
        f"{que} va a la ventana que esté delante, y «{snapshot.ventana}» no "
        "lo está: se lo llevaría otra. Ponla delante con un clic por patrón "
        "sobre ella, o actúa sobre el elemento con un ref en vez de a ciegas.",
        {"ventana": snapshot.ventana},
    )


def _actuar(
    accion: str, paso: dict, objetivo: Nodo | None, snapshot: Snapshot
) -> str:
    backend = _backend()
    from . import computer

    llega = entrada_global_llega(snapshot)

    if accion == "activar":
        # La salida del bloqueo, y la única forma de robar el foco: declarada,
        # visible en los pasos y contable después. Lo que se prohibió no es
        # tapar la pantalla, es taparla sin saberlo.
        if llega:
            return "ya estaba delante"
        traer = getattr(backend, "activar", None)
        if traer is None:
            raise ErrorUI(
                "sin_activar",
                "Este sistema no sabe traer una ventana al frente desde aquí. "
                "Pídeselo a quien esté delante del ordenador.",
            )
        if not traer(snapshot.handle):
            raise ErrorUI(
                "sin_primer_plano",
                f"El sistema no ha dejado poner «{snapshot.ventana}» "
                "delante. Pasa cuando otro programa retiene el foco. Puedes "
                "intentar "
                "lo que quieras por patrón —clic, escribir con ref— que eso "
                "no necesita primer plano.",
                {"ventana": snapshot.ventana},
            )
        return f'«{snapshot.ventana}» al frente'

    if accion == "tecla":
        _exigir_primer_plano(snapshot, "Pulsar una tecla")
        computer.pulsar(_texto_de(paso, "tecla"), paso.get("veces") or 1)
        return "teclado"

    elemento = _nativo_de(objetivo) if objetivo is not None else None

    if accion == "clic":
        return backend.clic(
            elemento,
            boton=str(paso.get("boton") or "left").lower(),
            veces=int(paso.get("veces") or 1),
            entrada_global=llega,
        )
    if accion == "escribir":
        if elemento is None:
            # Sin objetivo se escribe donde esté el foco. Es lo que hace un
            # teclado, y es lo que espera quien acaba de enfocar un campo en
            # el paso anterior; exigirle un ref otra vez era rechazarle algo
            # razonable y empujarle de vuelta a las capturas.
            _exigir_primer_plano(snapshot, "Escribir sin decir dónde")
            computer.teclear(_texto_de(paso, "texto"))
            return "teclado (donde estaba el foco)"
        return backend.escribir(
            elemento, _texto_de(paso, "texto"), entrada_global=llega
        )
    if accion == "desplazar":
        direccion = str(
            paso.get("direccion") or paso.get("texto") or "abajo"
        ).strip().lower()
        if direccion not in DIRECCIONES:
            raise ErrorUI(
                "direccion_desconocida",
                f"No sé desplazar «{direccion}». Las direcciones son: "
                f"{', '.join(DIRECCIONES)}.",
            )
        mover = getattr(backend, "desplazar", None)
        if mover is None:
            raise ErrorUI(
                "sin_desplazar",
                "Este sistema no sabe desplazar por patrón todavía. Usa "
                "devices_scroll sobre una captura.",
            )
        return mover(elemento, direccion, int(paso.get("veces") or 1))
    if accion == "seleccionar":
        return backend.seleccionar(elemento)
    if accion == "expandir":
        return backend.expandir(elemento)
    if accion == "contraer":
        return backend.contraer(elemento)
    if accion == "enfocar":
        backend.enfocar(elemento)
        return "foco"
    raise ErrorUI("accion_desconocida", f"No sé hacer «{accion}».")


# ---------- El lote ----------

def _verificar_escritura(
    snapshot: Snapshot, nombre: str, texto: str
) -> str | None:
    """Vuelve a leer la ventana y mira si el texto está donde lo pusimos.

    **Preguntarle al elemento que acabas de tocar no vale.** Medido en WhatsApp
    el 20/08/2026: `SetValue` no falla, el objeto devuelve luego el texto que le
    diste, y el cuadro de mensaje real se queda con un salto de línea. Es un
    «sí» que no significa nada, y de ahí salen los «ya te lo he enviado» de algo
    que no se envió. Lo único que dice la verdad es el árbol de después, que ya
    se relee igualmente en cada vuelta del lote.

    Devuelve `None` si entró, o el texto de lo que hay en su sitio si no. Si no
    se puede saber devuelve la cadena vacía, que no es lo mismo que un fallo.
    """
    backend = _backend()
    leer = getattr(backend, "valor_de", None)
    if leer is None or snapshot.raiz is None:
        return ""

    nombrar = getattr(backend, "nombre_de", None)
    candidatos = [
        n
        for n in ui_tree.recorrer_todos(snapshot.raiz)
        if n.nativo is not None
        and (n.nombre == nombre if nombre else False)
    ]
    if not candidatos and nombrar is not None:
        # Si el nombre cambió al escribir —los hay que se renombran con su
        # contenido—, se mira cualquier campo cuyo valor cuadre.
        candidatos = [
            n
            for n in ui_tree.recorrer_todos(snapshot.raiz)
            if n.nativo is not None and n.rol == "campo"
        ]
    if not candidatos:
        return ""

    visto = None
    for nodo in candidatos:
        try:
            valor = leer(nodo.nativo)
        except Exception:
            continue
        if valor is None:
            continue
        if ui_tree.texto_cuadra(valor, texto):
            return None
        if visto is None:
            visto = valor
    if visto is None:
        return ""
    return visto or "(vacío)"


def _validar(pasos: object) -> list[dict]:
    if not isinstance(pasos, list) or not pasos:
        raise ErrorUI("lote_vacio", "Un lote necesita al menos un paso.")
    if len(pasos) > MAX_PASOS:
        raise ErrorUI(
            "lote_largo",
            f"Un lote admite {MAX_PASOS} pasos como mucho y me has dado "
            f"{len(pasos)}. Pártelo y mira el resultado entre medias.",
        )
    limpios = []
    for indice, paso in enumerate(pasos, 1):
        if not isinstance(paso, dict):
            raise ErrorUI("paso_invalido", f"El paso {indice} no es un objeto.")
        accion = str(paso.get("accion") or "").strip().lower()
        if accion not in ACCIONES:
            raise ErrorUI(
                "accion_desconocida",
                f"El paso {indice} pide «{accion or 'nada'}». Las acciones "
                f"son: {', '.join(sorted(ACCIONES))}.",
            )
        limpios.append({**paso, "accion": accion})
    return limpios


def ejecutar_lote(pasos: object, ventana: str | None = None) -> dict:
    """Ejecuta la secuencia, para al primer fallo y devuelve siempre el árbol.

    El árbol final es la otra mitad del ahorro: cierra el ciclo ver → actuar →
    ver en un solo turno del modelo, que era el objetivo de todo esto.

    **El título de la ventana se resuelve una vez y ya no se vuelve a mirar.**
    Es la corrección de un fallo que se llevaba la mitad de los lotes rotos de
    este equipo: se releía el árbol por título después de cada paso, y hay
    ventanas que se retitulan solas —Spotify con la canción, Discord con el
    canal, un navegador con la pestaña—. Un lote de tres pasos moría a mitad
    con «no hay ninguna ventana que se llame "Spotify Free"» teniendo Spotify
    delante. El identificador que da el sistema no cambia mientras la ventana
    viva, así que se fija al principio y se trabaja contra él.
    """
    limpios = _validar(pasos)
    inicio = time.monotonic()
    hechos: list[dict] = []

    snapshot = _mirar(ventana)
    fijada = snapshot.handle

    for numero, paso in enumerate(limpios, 1):
        accion = paso["accion"]
        restante = PRESUPUESTO - (time.monotonic() - inicio)
        if restante <= 0:
            hechos.append({
                "n": numero,
                "accion": accion,
                "estado": "error",
                "error": "presupuesto_agotado",
                "detalle": (
                    f"Se han agotado los {PRESUPUESTO:.0f} s del lote antes "
                    "de este paso."
                ),
            })
            break

        try:
            if accion == "snapshot":
                snapshot = _mirar(ventana, handle=fijada)
                hechos.append({
                    "n": numero,
                    "accion": accion,
                    "estado": "ok",
                    "arbol": ui_tree.render(snapshot),
                })
                continue

            if accion == "esperar":
                descriptor = paso.get("buscar")
                espera = min(
                    float(paso.get("timeout_ms") or 1500) / 1000.0, restante
                )
                if not isinstance(descriptor, dict):
                    # Sin `buscar` es una pausa a secas. El modelo la pide
                    # constantemente entre pasos y es una necesidad real:
                    # exigirle decir a qué espera cuando solo quiere darle un
                    # momento a la ventana era rechazarle algo razonable.
                    pausa = min(espera, MAX_PAUSA)
                    time.sleep(max(0.0, pausa))
                    snapshot = _mirar(ventana, handle=fijada)
                    hechos.append({
                        "n": numero,
                        "accion": accion,
                        "estado": "ok",
                        "via": f"pausa de {pausa * 1000:.0f} ms",
                    })
                    continue
                encontrado, snapshot = _buscar_con_espera(
                    descriptor, snapshot, ventana, espera, fijada
                )
                hechos.append({
                    "n": numero,
                    "accion": accion,
                    "estado": "ok",
                    "via": f'apareció {encontrado.rol} "{encontrado.nombre}"',
                })
                continue

            objetivo = None
            ref = paso.get("ref")
            if ref:
                objetivo = Nodo(rol="", nativo=_por_ref(str(ref)))
            elif isinstance(paso.get("buscar"), dict):
                objetivo, snapshot = _buscar_con_espera(
                    paso["buscar"], snapshot, ventana, restante, fijada
                )
            elif accion in ACCIONES_CON_OBJETIVO:
                raise ErrorUI(
                    "falta_objetivo",
                    f"El paso {numero} («{accion}») no dice sobre qué "
                    "actuar: pásale un ref o un buscar.",
                )

            # Cómo se llamaba el campo ANTES de tocarlo: después hay que
            # buscarlo otra vez en el árbol nuevo, y con el texto dentro puede
            # haber cambiado de nombre.
            nombre_previo = ""
            if accion == "escribir" and objetivo is not None:
                nombrar = getattr(_backend(), "nombre_de", None)
                if nombrar is not None:
                    try:
                        nombre_previo = nombrar(_nativo_de(objetivo)) or ""
                    except Exception:
                        nombre_previo = ""

            via = _actuar(accion, paso, objetivo, snapshot)

            if accion == "escribir" and objetivo is not None:
                # Se relee aquí y no al final de la vuelta porque de esta
                # lectura depende si el paso cuenta como hecho.
                time.sleep(ESPERA_ASENTAR)
                snapshot = _mirar(ventana, handle=fijada)
                quedo = _verificar_escritura(
                    snapshot, nombre_previo, _texto_de(paso, "texto")
                )
                if quedo is None:
                    via = f"{via}, comprobado en la ventana"
                elif quedo == "":
                    via = f"{via} (sin comprobar: el campo no publica su valor)"
                else:
                    raise ErrorUI(
                        "no_entro",
                        f"El texto no ha entrado: «{nombre_previo or 'el campo'}» "
                        f"se ha quedado en «{quedo[:60]}». La llamada no ha "
                        "fallado, es que ese elemento acepta que le pongan "
                        "texto y no lo usa —les pasa a las aplicaciones web "
                        "metidas en una ventana—. Prueba con el campo de "
                        "escritura de verdad, o pon la ventana delante con un "
                        "paso `activar` y escribe con el teclado. **No des el "
                        "mensaje por escrito ni por enviado.**",
                        {"campo": nombre_previo, "quedo": quedo[:120]},
                    )

            hechos.append(
                {"n": numero, "accion": accion, "estado": "ok", "via": via}
            )

        except ErrorUI as error:
            hechos.append({
                "n": numero,
                "accion": accion,
                "estado": "error",
                "error": error.codigo,
                "detalle": error.mensaje,
                **({"datos": error.datos} if error.datos else {}),
            })
            break
        except Exception as error:  # pragma: no cover - fallo del sistema
            hechos.append({
                "n": numero,
                "accion": accion,
                "estado": "error",
                "error": "fallo",
                "detalle": f"{type(error).__name__}: {error}",
            })
            break

        # Después de tocar algo, la ventana necesita un momento para
        # asentarse; leerla a mitad de una animación da un árbol que no es ni
        # el de antes ni el de después.
        #
        # **Y esta relectura va dentro de un `try`**, aunque parezca de
        # trámite: si la ventana desaparece justo aquí —se cerró, la acción
        # anterior la cerró, el proceso murió— sin él la excepción se lleva por
        # delante el lote entero, y con él la lista de lo que sí se había
        # hecho. Quien lo recibe se queda sin saber por dónde iba, que es
        # exactamente la situación que hace falta evitar.
        time.sleep(ESPERA_ASENTAR)
        try:
            snapshot = _mirar(ventana, handle=fijada)
        except ErrorUI as error:
            hechos.append({
                "n": numero,
                "accion": "mirar",
                "estado": "error",
                "error": error.codigo,
                "detalle": (
                    f"{error.mensaje} Los pasos anteriores sí se hicieron; "
                    "lo que va después de este punto, no."
                ),
            })
            break

    fallo = next((h for h in hechos if h["estado"] == "error"), None)
    return {
        "pasos": hechos,
        "completados": sum(1 for h in hechos if h["estado"] == "ok"),
        "pedidos": len(limpios),
        "arbol": ui_tree.render(snapshot),
        "ventana": snapshot.ventana,
        "error": fallo["error"] if fallo else None,
        "ms": round((time.monotonic() - inicio) * 1000),
    }

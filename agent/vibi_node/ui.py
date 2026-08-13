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

ACCIONES_SIN_OBJETIVO = frozenset({"tecla", "snapshot", "esperar"})
ACCIONES = frozenset({
    "clic", "escribir", "tecla", "seleccionar", "expandir", "contraer",
    "enfocar", "esperar", "snapshot",
})


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


def _preparar(crudo: Nodo, rect, titulo, otras, aviso, expandir=None) -> Snapshot:
    """De árbol nativo a snapshot listo para leer: podar, colapsar, numerar."""
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
        raiz = ui_tree.asignar_refs(raiz, _registro)

    vistos = ui_tree.contar(raiz) if raiz is not None else 0
    return Snapshot(
        ventana=titulo,
        otras_ventanas=tuple(otras),
        raiz=raiz,
        totales=vistos,
        omitidos=max(0, total_crudo - vistos),
        aviso=aviso,
    )


def _mirar(ventana: str | None = None, expandir: str | None = None) -> Snapshot:
    global _ultimo
    backend = _backend()
    try:
        crudo, rect, titulo, otras, aviso = backend.capturar(ventana)
    except ErrorUI:
        raise
    except Exception as error:
        raise ErrorUI("sin_arbol", str(error)) from error
    _ultimo = _preparar(crudo, rect, titulo, otras, aviso, expandir)
    return _ultimo


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
    descriptor: dict, snapshot: Snapshot, ventana: str | None, limite: float
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
        actual = _mirar(ventana)


# ---------- Ejecutar un paso ----------

def _texto_de(paso: dict, clave: str) -> str:
    valor = paso.get(clave)
    if valor is None or str(valor) == "":
        raise ErrorUI(
            "falta_dato", f"Al paso «{paso.get('accion')}» le falta «{clave}»."
        )
    return str(valor)


def _actuar(accion: str, paso: dict, objetivo: Nodo | None) -> str:
    backend = _backend()
    from . import computer

    if accion == "tecla":
        computer.pulsar(_texto_de(paso, "tecla"), paso.get("veces") or 1)
        return "teclado"

    elemento = _nativo_de(objetivo) if objetivo is not None else None

    if accion == "clic":
        return backend.clic(
            elemento,
            boton=str(paso.get("boton") or "left").lower(),
            veces=int(paso.get("veces") or 1),
        )
    if accion == "escribir":
        return backend.escribir(elemento, _texto_de(paso, "texto"))
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
    """
    limpios = _validar(pasos)
    inicio = time.monotonic()
    hechos: list[dict] = []

    snapshot = _mirar(ventana)

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
                snapshot = _mirar(ventana)
                hechos.append({
                    "n": numero,
                    "accion": accion,
                    "estado": "ok",
                    "arbol": ui_tree.render(snapshot),
                })
                continue

            objetivo = None
            if accion not in ACCIONES_SIN_OBJETIVO:
                ref = paso.get("ref")
                if ref:
                    objetivo = Nodo(rol="", nativo=_por_ref(str(ref)))
                elif isinstance(paso.get("buscar"), dict):
                    objetivo, snapshot = _buscar_con_espera(
                        paso["buscar"], snapshot, ventana, restante
                    )
                else:
                    raise ErrorUI(
                        "falta_objetivo",
                        f"El paso {numero} («{accion}») no dice sobre qué "
                        "actuar: pásale un ref o un buscar.",
                    )

            if accion == "esperar":
                descriptor = paso.get("buscar")
                if not isinstance(descriptor, dict):
                    raise ErrorUI(
                        "falta_objetivo",
                        f"El paso {numero} («esperar») necesita un buscar.",
                    )
                espera = min(
                    float(paso.get("timeout_ms") or 1500) / 1000.0, restante
                )
                encontrado, snapshot = _buscar_con_espera(
                    descriptor, snapshot, ventana, espera
                )
                hechos.append({
                    "n": numero,
                    "accion": accion,
                    "estado": "ok",
                    "via": f'apareció {encontrado.rol} "{encontrado.nombre}"',
                })
                continue

            via = _actuar(accion, paso, objetivo)
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
        time.sleep(ESPERA_ASENTAR)
        snapshot = _mirar(ventana)

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

"""El teclado de esta máquina, hablando con Quartz directamente.

La pareja de `keyboard_windows` para macOS. Hasta ahora el Mac seguía tecleando
por la CLI `usecomputer`, y eso fallaba donde más duele:

- **WhatsApp no se enteraba del intro.** Medido el 2026-09-24: cuatro intros
  seguidos por `usecomputer` con el campo lleno y WhatsApp delante, todos
  contestados «ok», y el mensaje sin salir; un `keystroke return` de System
  Events lo mandó a la primera. `usecomputer` crea los eventos **sin fuente**
  (`CGEventCreateKeyboardEvent(NULL, …)`) y suelta la tecla en el mismo
  instante en que la baja; System Events, que sí funciona, las separa. Es la
  diferencia más probable —Catalyst y las web embebidas son conocidas por
  descartar esa pareja—, aunque no se ha aislado de la del proceso (abajo):
  aquí se corrigen las dos.
- **Cada pulsación arrancaba `npx`.** Entre 0,7 y 0,9 s por tecla: el lote de
  seis pasos del mensaje de WhatsApp tardó 4,6 s y aquí son milisegundos.
- **Y lo hacía otro proceso.** Quien tiene el permiso de Accesibilidad es el
  agente; lo que postea eventos sin ese permiso macOS lo tira sin decir nada, y
  la CLI volvía con código 0 igual. Aquí el evento sale del mismo proceso que
  lee el árbol, y si falta el permiso se dice en vez de fingir que se tecleó.

**El texto va como Unicode, carácter a carácter,** por la misma razón que en
Windows: con códigos de tecla, una «ñ» o un «@» dependen de la distribución del
teclado. `CGEventKeyboardSetUnicodeString` admite hasta 20 unidades por evento,
pero hay aplicaciones que de un evento con varias letras solo cogen la primera;
uno por carácter es lo que nunca pierde nada.

Las combinaciones («cmd+a») sí van por código de tecla, porque un atajo es una
posición del teclado y no una letra. Los códigos son los de la distribución ANSI
(`kVK_ANSI_*`), que macOS traduce igual en un teclado español para los atajos.
"""
from __future__ import annotations

import time

# Cuánto se espera entre bajar y soltar una tecla, y después de soltarla.
#
# Sin separación, la pareja llega a la vez y es lo que WhatsApp parece
# descartar. 8 ms es imperceptible: un intro entero son 16 ms.
ESPERA_TECLA = 0.008

# Entre carácter y carácter de un texto. Más corta que la de una tecla porque
# aquí el riesgo no es que se ignore el evento sino que se desordene, y eso no
# pasa con los eventos de una misma fuente.
ESPERA_CARACTER = 0.002

# `kVK_*` de `HIToolbox/Events.h`. Se aceptan en español y en inglés por lo
# mismo que en Windows: el prompt está en español y `devices.key` promete
# nombres en inglés, y el modelo mezcla los dos.
CODIGOS = {
    "enter": 0x24, "intro": 0x24, "return": 0x24,
    "tab": 0x30, "tabulador": 0x30,
    "escape": 0x35, "esc": 0x35,
    "space": 0x31, "espacio": 0x31,
    "backspace": 0x33, "retroceso": 0x33,
    "delete": 0x75, "supr": 0x75, "suprimir": 0x75,
    "up": 0x7E, "arriba": 0x7E,
    "down": 0x7D, "abajo": 0x7D,
    "left": 0x7B, "izquierda": 0x7B,
    "right": 0x7C, "derecha": 0x7C,
    "home": 0x73, "inicio": 0x73,
    "end": 0x77, "fin": 0x77,
    "pageup": 0x74, "pgup": 0x74, "repag": 0x74,
    "pagedown": 0x79, "pgdown": 0x79, "avpag": 0x79,
    "capslock": 0x39, "bloqmayus": 0x39,
    "volumeup": 0x48, "volumedown": 0x49, "volumemute": 0x4A,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
}

# Las letras, números y signos por su posición en un teclado ANSI.
CARACTERES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12,
    "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18,
    "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E,
    "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23, "l": 0x25,
    "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29, "\\": 0x2A, ",": 0x2B,
    "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F, "`": 0x32,
}

# Cada modificador: su tecla y la bandera que tiene que llevar el evento. Las
# dos hacen falta: la tecla para quien mira qué se pulsó, la bandera para quien
# solo mira el evento de la tecla principal, que es casi todo el mundo.
MODIFICADORES = {
    "cmd": (0x37, 0x100000), "command": (0x37, 0x100000),
    "meta": (0x37, 0x100000), "super": (0x37, 0x100000),
    "win": (0x37, 0x100000),
    "shift": (0x38, 0x20000), "mayus": (0x38, 0x20000),
    "alt": (0x3A, 0x80000), "option": (0x3A, 0x80000), "opt": (0x3A, 0x80000),
    "ctrl": (0x3B, 0x40000), "control": (0x3B, 0x40000),
    "fn": (0x3F, 0x800000),
}


class ErrorTeclado(Exception):
    pass


def _quartz():
    try:
        import Quartz
    except ImportError as error:  # pragma: no cover - depende de la máquina
        raise ErrorTeclado(
            "Falta pyobjc en esta máquina. Instálalo con "
            "«pip install -r agent/requirements.txt»."
        ) from error
    return Quartz


def _exigir_permiso(quartz) -> None:
    """Sin permiso, macOS tira los eventos en silencio: mejor decirlo."""
    comprobar = getattr(quartz, "CGPreflightPostEventAccess", None)
    if comprobar is None or comprobar():
        return
    raise ErrorTeclado(
        "Vibi no tiene permiso para teclear en este Mac y macOS descartaría las "
        "pulsaciones sin avisar. Concédelo en Ajustes del Sistema › Privacidad "
        "y seguridad › Accesibilidad, marcando la aplicación desde la que corre "
        "el agente, y vuelve a intentarlo."
    )


def _preparar():
    quartz = _quartz()
    _exigir_permiso(quartz)
    # Con fuente del estado del sistema, el evento se parece a uno de un
    # teclado de verdad; sin ella es el que descartan Catalyst y las web.
    fuente = quartz.CGEventSourceCreate(quartz.kCGEventSourceStateHIDSystemState)
    return quartz, fuente


def _postear(quartz, evento) -> None:
    if evento is None:
        raise ErrorTeclado("macOS no dejó crear el evento de teclado")
    quartz.CGEventPost(quartz.kCGHIDEventTap, evento)


def _tecla(quartz, fuente, codigo: int, bajar: bool, banderas: int) -> None:
    evento = quartz.CGEventCreateKeyboardEvent(fuente, codigo, bajar)
    if evento is not None:
        quartz.CGEventSetFlags(evento, banderas)
    _postear(quartz, evento)


# ---------- Traducción ----------

def traducir(tecla: str) -> tuple[tuple[tuple[int, int], ...], int]:
    """De «cmd+shift+t» a los modificadores y el código de la tecla.

    Se acepta el guion además del más porque el modelo escribe las dos formas.
    """
    crudo = str(tecla or "").strip()
    if not crudo:
        raise ErrorTeclado("No has dicho qué tecla pulsar")

    plano = crudo.casefold()
    # «-» suelto es una tecla, no un separador.
    partes = [plano] if plano == "-" else plano.replace("-", "+").split("+")
    if any(not parte.strip() for parte in partes):
        raise ErrorTeclado(
            f"«{crudo}» no está completa: falta la tecla después del «+»."
        )
    partes = [parte.strip() for parte in partes]

    *nombres_modificadores, nombre_tecla = partes
    modificadores = []
    for nombre in nombres_modificadores:
        modificador = MODIFICADORES.get(nombre)
        if modificador is None:
            raise ErrorTeclado(
                f"No sé qué modificador es «{nombre}». Uso cmd, ctrl, alt, "
                "shift o fn."
            )
        modificadores.append(modificador)

    codigo = CODIGOS.get(nombre_tecla, CARACTERES.get(nombre_tecla))
    if codigo is None:
        raise ErrorTeclado(
            f"No sé qué tecla es «{nombre_tecla}». Dime «enter», «tab», "
            f"«escape», una letra, o una combinación como «cmd+s»."
        )
    return tuple(modificadores), codigo


# ---------- Acciones ----------

def pulsar(tecla: str, veces: int = 1) -> dict:
    """Pulsa una tecla o una combinación: «enter», «cmd+a», «cmd+shift+t».

    Los modificadores se sueltan en orden inverso, como en Windows y por lo
    mismo: soltarlos en el orden en que se bajaron deja uno pulsado cuando la
    tecla ya subió.
    """
    modificadores, codigo = traducir(tecla)
    repeticiones = max(1, min(int(veces or 1), 50))
    quartz, fuente = _preparar()

    banderas = 0
    for _, bandera in modificadores:
        banderas |= bandera

    for _ in range(repeticiones):
        acumuladas = 0
        for codigo_modificador, bandera in modificadores:
            acumuladas |= bandera
            _tecla(quartz, fuente, codigo_modificador, True, acumuladas)
        _tecla(quartz, fuente, codigo, True, banderas)
        time.sleep(ESPERA_TECLA)
        _tecla(quartz, fuente, codigo, False, banderas)
        for codigo_modificador, bandera in reversed(modificadores):
            acumuladas &= ~bandera
            _tecla(quartz, fuente, codigo_modificador, False, acumuladas)
        time.sleep(ESPERA_TECLA)
    return {"accion": "pulsar", "tecla": str(tecla).strip(), "veces": repeticiones}


def _caracter(quartz, fuente, letra: str) -> None:
    unidades = len(letra.encode("utf-16-le")) // 2
    for bajar in (True, False):
        # Código 0 y el carácter encima: el código no cuenta cuando hay texto.
        evento = quartz.CGEventCreateKeyboardEvent(fuente, 0, bajar)
        if evento is not None:
            quartz.CGEventSetFlags(evento, 0)
            quartz.CGEventKeyboardSetUnicodeString(evento, unidades, letra)
        _postear(quartz, evento)
        time.sleep(ESPERA_CARACTER)


def teclear(texto: str) -> dict:
    """Escribe texto donde esté el foco, carácter a carácter."""
    texto = str(texto or "")
    if not texto:
        raise ErrorTeclado("No has dicho qué escribir")

    quartz, fuente = _preparar()
    for letra in texto:
        if letra == "\n":
            # Como carácter Unicode no hace nada en casi ninguna ventana.
            _tecla(quartz, fuente, CODIGOS["enter"], True, 0)
            time.sleep(ESPERA_TECLA)
            _tecla(quartz, fuente, CODIGOS["enter"], False, 0)
        elif letra == "\r":
            continue  # el \n del par ya puso el intro
        else:
            _caracter(quartz, fuente, letra)
    return {"accion": "teclear", "caracteres": len(texto)}

"""El teclado de esta máquina, hablando con Windows directamente.

La otra mitad de `mouse_windows`. El ratón se trajo aquí porque `usecomputer`
se caía al moverlo; el teclado sí funcionaba y se quedó en la CLI. Se trae
igualmente, y no por un fallo sino porque la dependencia dejó de tener sentido:

- **`usecomputer` está parado.** 0.1.11 es la última publicada, del 7 de abril
  de 2026. Era lo único que ataba el nodo a Node y a `npx`.
- **Cada pulsación arrancaba un proceso.** Bajar diez líneas eran diez procesos.
- **Y había un techo absurdo.** El texto iba como argumento de la línea de
  comandos, que en Windows tiene 32.767 caracteres; pasado eso había que
  cambiar a stdin. Aquí no hay línea de comandos, así que no hay techo.

**El texto se manda como Unicode y no como códigos de tecla.** Es la decisión
que importa: con códigos, lo que sale depende de la distribución del teclado
—una «ñ» o un «@» no están en el mismo sitio en un teclado español que en uno
inglés—, y Vibi escribe texto que le ha dado una persona en español. Con
`KEYEVENTF_UNICODE` se manda el carácter y Windows lo entrega tal cual.

La excepción es el salto de línea: como carácter Unicode no hace nada en casi
ninguna ventana, así que se traduce a un intro de verdad.
"""
from __future__ import annotations

import ctypes
import time

# Las estructuras y el envío son los mismos que mueven el ratón; tenerlas dos
# veces sería tener dos definiciones de `INPUT` que un día no coinciden.
from .mouse_windows import (
    INPUT,
    INPUT_KEYBOARD,
    KEYBDINPUT,
    KEYEVENTF_KEYUP,
    MODIFICADORES,
    user32,
)

KEYEVENTF_UNICODE = 0x0004

# Cuánto se espera entre una pulsación repetida y la siguiente.
#
# Bajar y soltar van en un solo `SendInput`, así que ahí no hace falta nada: la
# pareja entra en la cola junta y ninguna aplicación la ve partida. Esto es solo
# la separación entre repeticiones de `pulsar(tecla, veces)`.
#
# Medido el 2026-08-15 contra un control EDIT propio, pulsando 20 veces: con
# **cero** espera llegan las 20 y cuesta 13 ms; con 30 ms llegan las 20 y cuesta
# 622. O sea que para entregar no hace falta ninguna. Se deja un valor pequeño
# como seguro y no por medida: un EDIT es el receptor más dócil que hay, y no se
# ha probado contra una aplicación que limite su propia entrada —una lista con
# desplazamiento suave, un editor con repetición propia—, que es donde una
# ráfaga instantánea podría colapsarse en una sola pulsación.
ESPERA_PULSACION = 0.008

# Cuántos eventos se mandan de una. La cola de entrada de Windows no es
# infinita y un texto largo entero de golpe se entrega a medias sin avisar.
MAX_EVENTOS_POR_ENVIO = 400

# Los nombres que puede decir el modelo, y lo que Windows entiende por ellos.
# Se aceptan en español y en inglés porque el prompt está en español y el
# vocabulario que promete `devices.key` está en inglés: quien escribe la orden
# mezcla los dos sin pensarlo.
VK_TECLAS = {
    "enter": 0x0D, "intro": 0x0D, "return": 0x0D,
    "tab": 0x09, "tabulador": 0x09,
    "escape": 0x1B, "esc": 0x1B,
    "space": 0x20, "espacio": 0x20,
    "backspace": 0x08, "retroceso": 0x08,
    "delete": 0x2E, "supr": 0x2E, "suprimir": 0x2E,
    "insert": 0x2D,
    "up": 0x26, "arriba": 0x26,
    "down": 0x28, "abajo": 0x28,
    "left": 0x25, "izquierda": 0x25,
    "right": 0x27, "derecha": 0x27,
    "home": 0x24, "inicio": 0x24,
    "end": 0x23, "fin": 0x23,
    "pageup": 0x21, "pgup": 0x21, "repag": 0x21,
    "pagedown": 0x22, "pgdown": 0x22, "avpag": 0x22,
    "printscreen": 0x2C, "imprpant": 0x2C,
    "capslock": 0x14, "bloqmayus": 0x14,
    # Las de multimedia, que son las que mueve `media.py` cuando no hay sesión.
    "volumeup": 0xAF, "volumedown": 0xAE, "volumemute": 0xAD,
    "playpause": 0xB3, "nexttrack": 0xB0, "prevtrack": 0xB1,
}
VK_TECLAS.update({f"f{numero}": 0x6F + numero for numero in range(1, 25)})


class ErrorTeclado(Exception):
    pass


def _enviar(*entradas: INPUT) -> None:
    cuantas = len(entradas)
    array = (INPUT * cuantas)(*entradas)
    enviados = user32.SendInput(cuantas, array, ctypes.sizeof(INPUT))
    if enviados != cuantas:
        raise ErrorTeclado(
            "Windows no aceptó la orden del teclado. Suele pasar cuando hay "
            "delante una ventana con más privilegios que Vibi."
        )


def _codigo(codigo: int, soltar: bool = False) -> INPUT:
    """Un evento de tecla por código virtual."""
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=codigo, wScan=0,
            dwFlags=KEYEVENTF_KEYUP if soltar else 0,
            time=0, dwExtraInfo=None,
        ),
    )


def _caracter(letra: str, soltar: bool = False) -> INPUT:
    """Un evento de tecla por carácter, sin pasar por la distribución."""
    banderas = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if soltar else 0)
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=0, wScan=ord(letra), dwFlags=banderas,
            time=0, dwExtraInfo=None,
        ),
    )


# ---------- Traducción ----------

def _plano(texto: str) -> str:
    return texto.strip().casefold()


def traducir(tecla: str) -> tuple[tuple[int, ...], int]:
    """De «ctrl+shift+t» a los modificadores y la tecla que quiere Windows.

    Se acepta el guion además del más porque el modelo escribe las dos formas
    y ninguna es más correcta que la otra.
    """
    crudo = str(tecla or "").strip()
    if not crudo:
        raise ErrorTeclado("No has dicho qué tecla pulsar")

    partes = [p for p in _plano(crudo).replace("-", "+").split("+")]
    if any(not parte.strip() for parte in partes):
        raise ErrorTeclado(
            f"«{crudo}» no está completa: falta la tecla después del «+»."
        )
    partes = [parte.strip() for parte in partes]

    *nombres_modificadores, nombre_tecla = partes
    modificadores = []
    for nombre in nombres_modificadores:
        codigo = MODIFICADORES.get(nombre)
        if codigo is None:
            raise ErrorTeclado(
                f"No sé qué modificador es «{nombre}». Uso ctrl, shift, alt o win."
            )
        modificadores.append(codigo)

    codigo = VK_TECLAS.get(nombre_tecla)
    if codigo is None:
        if len(nombre_tecla) == 1:
            # Una letra o un número: su código virtual es el del carácter en
            # mayúscula. Vale para «ctrl+s» y para «alt+f4» ya cubierto arriba.
            codigo = ord(nombre_tecla.upper())
        else:
            raise ErrorTeclado(
                f"No sé qué tecla es «{nombre_tecla}». Dime «enter», «tab», "
                f"«escape», una letra, o una combinación como «ctrl+s»."
            )
    return tuple(modificadores), codigo


# ---------- Acciones ----------

def pulsar(tecla: str, veces: int = 1) -> dict:
    """Pulsa una tecla o una combinación: «enter», «ctrl+s», «alt+tab».

    Los modificadores se sueltan **en orden inverso**: bajar ctrl, bajar shift,
    bajar la tecla, soltar la tecla, soltar shift, soltar ctrl. Soltarlos en el
    mismo orden en que se bajaron deja un modificador pulsado cuando la tecla ya
    subió, y hay aplicaciones que leen eso como otro atajo.
    """
    modificadores, codigo = traducir(tecla)
    repeticiones = max(1, min(int(veces or 1), 50))

    for _ in range(repeticiones):
        entradas = [_codigo(m) for m in modificadores]
        entradas.append(_codigo(codigo))
        entradas.append(_codigo(codigo, soltar=True))
        entradas.extend(_codigo(m, soltar=True) for m in reversed(modificadores))
        _enviar(*entradas)
        if repeticiones > 1:
            time.sleep(ESPERA_PULSACION)
    return {"accion": "pulsar", "tecla": str(tecla).strip(), "veces": repeticiones}


def teclear(texto: str) -> dict:
    """Escribe texto donde esté el foco, carácter a carácter.

    Va en un solo `SendInput` por tramo y no uno por letra: cada llamada es un
    salto al sistema, y un párrafo son cientos. Se corta en tramos porque la
    cola de entrada de Windows tiene tope y un texto enorme de una vez se
    pierde a medias sin decir nada.
    """
    texto = str(texto or "")
    if not texto:
        raise ErrorTeclado("No has dicho qué escribir")

    entradas: list[INPUT] = []
    for letra in texto:
        if letra == "\n":
            # Como carácter Unicode no hace nada en casi ninguna ventana.
            entradas.append(_codigo(VK_TECLAS["enter"]))
            entradas.append(_codigo(VK_TECLAS["enter"], soltar=True))
        elif letra == "\r":
            continue  # el \n del par ya puso el intro
        else:
            entradas.append(_caracter(letra))
            entradas.append(_caracter(letra, soltar=True))

    for inicio in range(0, len(entradas), MAX_EVENTOS_POR_ENVIO):
        _enviar(*entradas[inicio:inicio + MAX_EVENTOS_POR_ENVIO])
    return {"accion": "teclear", "caracteres": len(texto)}

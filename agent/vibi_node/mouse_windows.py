"""El ratón de esta máquina, hablando con Windows directamente.

`computer.py` pilota el ratón y el teclado a través de la CLI `usecomputer`.
El teclado funciona; **el ratón no**: la versión 0.1.11 se cae con «instrucción
ilegal» en todo lo que mueve el puntero —clic, hover, arrastre y rueda— y esa
es la última publicada, del 7 de abril de 2026. No hay actualización que
esperar, así que el ratón se hace aquí.

Detrás está `SendInput`, que es la misma API que usaría cualquier programa de
automatización y la que `usecomputer` intenta usar por dentro. Medido en este
equipo: 0,6 ms por movimiento, contra el proceso entero que había que arrancar
antes.

**Las coordenadas son las del escritorio, no las de ninguna captura.** La
traducción desde la imagen que ve el modelo sigue en `computer.py`, que es
donde estaba; aquí se recibe ya en píxeles reales, con el origen donde lo
tenga el escritorio virtual —que con dos monitores puede ser negativo, y en
este equipo lo es—.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

# El escritorio virtual: todos los monitores juntos, con su origen real.
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002

# Lo que Windows entiende por una muesca de rueda.
RUEDA = 120

BOTONES = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

MODIFICADORES = {
    "ctrl": 0x11, "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B, "meta": 0x5B, "cmd": 0x5B,
}


class ErrorRaton(Exception):
    pass


# ---------- Las estructuras de SendInput ----------

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _enviar(*entradas: INPUT) -> None:
    cuantas = len(entradas)
    array = (INPUT * cuantas)(*entradas)
    enviados = user32.SendInput(cuantas, array, ctypes.sizeof(INPUT))
    if enviados != cuantas:
        raise ErrorRaton(
            "Windows no aceptó la orden del ratón. Suele pasar cuando hay "
            "delante una ventana con más privilegios que Vibi."
        )


def _raton(flags: int, dx: int = 0, dy: int = 0, datos: int = 0) -> INPUT:
    return INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(
            dx=dx, dy=dy, mouseData=datos, dwFlags=flags,
            time=0, dwExtraInfo=None,
        ),
    )


def _tecla(codigo: int, soltar: bool = False) -> INPUT:
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=codigo, wScan=0,
            dwFlags=KEYEVENTF_KEYUP if soltar else 0,
            time=0, dwExtraInfo=None,
        ),
    )


# ---------- Movimiento ----------

def posicion() -> tuple[int, int]:
    punto = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(punto))
    return int(punto.x), int(punto.y)


def _absoluto(x: int, y: int) -> tuple[int, int]:
    """De píxeles del escritorio a las 0..65535 que quiere SendInput."""
    izquierda = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    arriba = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    ancho = max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) - 1)
    alto = max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) - 1)
    return (
        int(round((x - izquierda) * 65535 / ancho)),
        int(round((y - arriba) * 65535 / alto)),
    )


def mover(x: int, y: int) -> None:
    """Lleva el puntero a un punto del escritorio.

    Se manda el movimiento con `SendInput` y después se clava con
    `SetCursorPos`. Lo primero es lo que genera el evento que las aplicaciones
    escuchan —sin él, muchas no se enteran de que el ratón ha pasado por
    encima—; lo segundo corrige el píxel que se pierde al convertir a la
    escala de 0 a 65535, que sobre un escritorio de 3.840 px de ancho es
    justo eso, un píxel.
    """
    dx, dy = _absoluto(x, y)
    _enviar(_raton(
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        dx, dy,
    ))
    user32.SetCursorPos(int(x), int(y))


# ---------- Botones ----------

def _intervalo_doble_clic() -> float:
    """Lo que el sistema considera un doble clic, con margen.

    Lo configura la persona en su panel de control, así que preguntarlo es más
    fiable que dar por bueno un número. Se usa la mitad para que dos clics
    seguidos caigan holgadamente dentro.
    """
    try:
        return max(0.02, user32.GetDoubleClickTime() / 1000.0 / 2)
    except Exception:
        return 0.05


def clic(
    x: int | None = None,
    y: int | None = None,
    boton: str = "left",
    veces: int = 1,
    modificadores: tuple[str, ...] = (),
) -> None:
    """Pulsa, con los modificadores que se pidan."""
    boton = (boton or "left").strip().lower()
    if boton not in BOTONES:
        raise ErrorRaton(f"«{boton}» no es un botón: usa left, right o middle")

    if x is not None and y is not None:
        mover(int(x), int(y))

    codigos = []
    for nombre in modificadores:
        codigo = MODIFICADORES.get(str(nombre).strip().lower())
        if codigo is None:
            raise ErrorRaton(
                f"No conozco el modificador «{nombre}»: usa ctrl, shift, alt o win"
            )
        codigos.append(codigo)

    abajo, arriba = BOTONES[boton]
    for codigo in codigos:
        _enviar(_tecla(codigo))
    try:
        for numero in range(max(1, int(veces))):
            if numero:
                time.sleep(_intervalo_doble_clic())
            _enviar(_raton(abajo), _raton(arriba))
    finally:
        # Los modificadores se sueltan pase lo que pase: dejar el Ctrl
        # pulsado convierte cualquier tecla posterior en un atajo.
        for codigo in reversed(codigos):
            _enviar(_tecla(codigo, soltar=True))


def arrastrar(desde_x: int, desde_y: int, hasta_x: int, hasta_y: int,
              boton: str = "left") -> None:
    """Arrastra de un punto a otro con el botón pulsado.

    El recorrido va por pasos y no de un salto: un arrastre que aparece
    directamente en el destino no lo reconocen ni las listas ordenables ni los
    lienzos, que necesitan ver el movimiento.
    """
    boton = (boton or "left").strip().lower()
    if boton not in BOTONES:
        raise ErrorRaton(f"«{boton}» no es un botón: usa left, right o middle")
    abajo, arriba = BOTONES[boton]

    mover(int(desde_x), int(desde_y))
    _enviar(_raton(abajo))
    try:
        pasos = 24
        for paso in range(1, pasos + 1):
            mover(
                int(desde_x + (hasta_x - desde_x) * paso / pasos),
                int(desde_y + (hasta_y - desde_y) * paso / pasos),
            )
            time.sleep(0.008)
    finally:
        _enviar(_raton(arriba))


def desplazar(direccion: str, cantidad: int = 3,
              en: tuple[int, int] | None = None) -> None:
    """Mueve la rueda. La rueda gira donde esté el puntero, no donde el foco."""
    direccion = (direccion or "").strip().lower()
    if en is not None:
        mover(int(en[0]), int(en[1]))

    if direccion in ("up", "arriba"):
        flags, datos = MOUSEEVENTF_WHEEL, RUEDA
    elif direccion in ("down", "abajo"):
        flags, datos = MOUSEEVENTF_WHEEL, -RUEDA
    elif direccion in ("left", "izquierda"):
        flags, datos = MOUSEEVENTF_HWHEEL, -RUEDA
    elif direccion in ("right", "derecha"):
        flags, datos = MOUSEEVENTF_HWHEEL, RUEDA
    else:
        raise ErrorRaton(
            f"«{direccion}» no es una dirección: usa up, down, left o right"
        )

    for numero in range(max(1, int(cantidad))):
        if numero:
            time.sleep(0.02)
        _enviar(_raton(flags, datos=datos))

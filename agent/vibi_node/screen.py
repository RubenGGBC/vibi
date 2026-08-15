"""Lo que se ve ahora mismo en las pantallas de esta máquina.

En macOS se captura con lo que ya trae el sistema —`screencapture` y `sips`—.
En Windows se hacía igual, con `System.Windows.Forms` a través de PowerShell, y
se dejó de hacer: **medido el 2026-08-15 en este equipo, esa vía costaba 1.229 ms
por foto y 10,5 s la primera vez de cada proceso.** Como cada captura arrancaba
un `powershell.exe` nuevo, la «primera vez» era todas. La misma imagen exacta
—JPEG de 1568 px— sale en 60,6 ms con `mss`, que es Python puro sobre ctypes.
Veinte veces. Con el ciclo mirar → tocar → mirar pagando eso dos veces, no era
un detalle de rendimiento sino el coste de mirar.

El reparto entre lo común y lo de cada sistema es deliberado: **entender qué
pantalla te han pedido se hace una vez, medirla y fotografiarla se hace por
sistema.** Traducir «la de la derecha» a un monitor no cambia entre sistemas, y
tenerlo dos veces era garantizar que un día dijeran cosas distintas — que es
justo lo que pasaba mientras Windows elegía dentro del PowerShell y macOS en
Python. Ahora los dos aportan la geometría en el mismo formato (`_pantallas_*`)
y quien elige es `_elegir`, para los dos.

La imagen sale ya reducida y en JPEG. Un 4K en PNG son ocho megas que ningún
modelo va a mirar a esa resolución: se recorta el lado largo a 1568 px, que es
lo que aprovecha la API, y el resto es peso que solo serviría para pagar
transferencia.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

# El lado largo de la imagen que se manda. Por encima de esto la API reescala
# igualmente, así que subirlo solo cuesta ancho de banda y tiempo de subida.
LADO_MAXIMO = 1568
CALIDAD_JPEG = 80

# Solo lo usa macOS, que sigue saliendo a dos procesos por foto (`screencapture`
# y `sips`). Con margen para una máquina cargada.
TIMEOUT_CAPTURA = 45


class ErrorPantalla(Exception):
    pass


def _medida_reducida(ancho: int, alto: int) -> tuple[int, int]:
    """A cuánto encoge una captura de `ancho`×`alto`, guardando la proporción.

    Solo encoge: una pantalla que ya cabe se manda tal cual, porque agrandarla
    no añade ni un píxel de información y sí de peso. El mínimo de 1 px es para
    la geometría absurda —un rectángulo de 4000×1 al redondear daría cero— y no
    para ninguna pantalla real.
    """
    escala = min(1.0, LADO_MAXIMO / max(ancho, alto))
    if escala >= 1.0:
        return ancho, alto
    return max(1, round(ancho * escala)), max(1, round(alto * escala))


# ---------- Qué pantalla te han pedido ----------

# Los tokens canónicos que entiende el script nativo. La lista de sinónimos es
# larga a propósito: esto lo rellena un modelo con lo que haya dicho una
# persona, y «la de la derecha», «pantalla 2» y «la secundaria» pueden ser todas
# la misma y hay que aceptarlas las tres.
_ALIAS = {
    "cursor": (
        "", "cursor", "raton", "el raton", "donde esta el raton", "mouse",
        "actual", "la actual", "esta", "esta pantalla", "aqui", "activa",
        "la activa", "donde estoy", "current",
    ),
    "principal": (
        "principal", "la principal", "primaria", "la primaria", "primera",
        "la primera", "main", "primary", "1", "pantalla 1", "monitor 1",
    ),
    "secundaria": (
        "secundaria", "la secundaria", "secundario", "segunda", "la segunda",
        "otra", "la otra", "second", "secondary", "2", "pantalla 2",
        "monitor 2",
    ),
    "izquierda": (
        "izquierda", "la izquierda", "izq", "la de la izquierda", "left",
    ),
    "derecha": (
        "derecha", "la derecha", "der", "la de la derecha", "right",
    ),
    "arriba": ("arriba", "la de arriba", "superior", "encima", "top", "upper"),
    "abajo": ("abajo", "la de abajo", "inferior", "debajo", "bottom", "lower"),
    "todas": (
        "todas", "todas las pantallas", "todo", "ambas", "las dos", "completa",
        "escritorio", "all", "both", "everything",
    ),
}

# «1» y «2» ya viven arriba como principal y secundaria, que es lo que quiere
# decir la gente al numerarlas. De la tercera en adelante no hay nombre común y
# se va por número de orden.
_MAXIMO_NUMERADO = 16


def _plano(texto: str) -> str:
    """Sin tildes, sin mayúsculas y sin espacios de más."""
    sin_tildes = "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caracter) != "Mn"
    )
    return " ".join(sin_tildes.casefold().split())


def normalizar(pedido: object) -> str:
    """Traduce lo que dijo la persona al token que entiende el script nativo.

    Ante algo que no reconoce no inventa una pantalla: lo dice. Devolver el
    monitor principal «por si acaso» sería enseñarle al usuario una pantalla que
    no ha pedido y dejarle creer que es la que quería.
    """
    texto = _plano(str(pedido or ""))
    for token, alias in _ALIAS.items():
        if texto in alias:
            return token

    # «pantalla 3», «la pantalla 3», «el monitor 3», «3»: se van quitando
    # palabras de delante hasta que solo queda el número. En bucle y no de una
    # pasada, porque se encadenan: «la pantalla 3» lleva dos.
    numero = texto
    while True:
        for prefijo in ("la ", "el ", "pantalla ", "monitor ", "numero "):
            if numero.startswith(prefijo):
                numero = numero[len(prefijo):].strip()
                break
        else:
            break
    if numero.isdigit() and 1 <= int(numero) <= _MAXIMO_NUMERADO:
        return f"n{int(numero)}"

    raise ErrorPantalla(
        f"No sé qué pantalla es «{pedido}». Dime «la principal», «la "
        f"secundaria», «la de la izquierda», «la de la derecha», un número, o "
        f"no digas nada y cojo la que tenga el ratón."
    )


# ---------- Windows ----------

# Windows describe el escritorio en píxeles reales solo si el proceso declara
# que entiende el escalado. Sin esto miente sobre el tamaño de cada pantalla, y
# con dos monitores a escalados distintos los rectángulos dejan de encajar: la
# captura de uno se lleva un trozo del otro.
#
# **Se declara aquí y no en `mss`, que también lo haría.** Es un ajuste de todo
# el proceso y de una sola dirección, así que quien lo ponga decide en qué
# sistema de coordenadas vive el agente entero —`mouse_windows` y el árbol de
# UIA incluidos—. Dejarlo al azar de qué módulo se importe primero es pedir que
# un día el ratón y la foto no hablen del mismo píxel.
#
# Y por eso lo llama el arranque (`__main__._arrancar`) y no solo la primera
# captura: si se declarase al fotografiar, en una máquina con escalado el
# escritorio mediría una cosa antes de la primera foto y otra después, y las
# coordenadas del ratón cambiarían a mitad de sesión.
#
# Se usa el modo de sistema (`SetProcessDPIAware`) y no el por monitor, que es
# el que declaraba el script de PowerShell al que esto sustituye: cambiar de
# captura no debía cambiar además la geometría.
_dpi_declarado = False


def declarar_dpi() -> None:
    """Fija el sistema de coordenadas del proceso. Fuera de Windows no hace nada."""
    global _dpi_declarado
    if _dpi_declarado or platform.system() != "Windows":
        return
    import ctypes  # noqa: PLC0415 - solo en Windows

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # pragma: no cover - versiones antiguas de Windows
        pass
    _dpi_declarado = True


def _importar(modulo: str, paquete: str):
    """Trae una dependencia de escritorio, o dice cuál falta y cómo ponerla.

    Se importa dentro de las funciones y no arriba a propósito: el agente tiene
    que arrancar en un equipo al que le falte esto y fallar solo al pedirle una
    foto, no al encenderlo. Y el error tiene que ser `ErrorPantalla` porque es
    el único que `capabilities` sabe convertir en una frase para el chat; un
    `ImportError` crudo llegaría como un fallo sin explicación.
    """
    try:
        return __import__(modulo, fromlist=["_"])
    except ImportError as error:
        raise ErrorPantalla(
            f"Me falta «{paquete}» para poder fotografiar la pantalla. "
            f"Instálalo con:  pip install {paquete}"
        ) from error


def _pantallas_windows() -> list[dict]:
    """La geometría de los monitores y dónde está el ratón.

    Mismo formato que `_pantallas_mac`, porque quien elige después es `_elegir`
    y es el mismo código para los dos sistemas.

    La principal se reconoce por estar en el origen: Windows define el
    escritorio virtual poniéndola en (0, 0), y de ahí que los monitores a su
    izquierda tengan la x negativa.
    """
    import ctypes  # noqa: PLC0415 - solo en Windows

    declarar_dpi()
    mss = _importar("mss", "mss")

    class _Punto(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    cursor = _Punto()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor))

    with mss.MSS() as sct:
        # El primero es el escritorio virtual entero; los monitores vienen
        # detrás. Aquí solo interesan los de verdad.
        crudos = list(sct.monitors[1:])

    pantallas = []
    for numero, monitor in enumerate(crudos, start=1):
        x, y = monitor["left"], monitor["top"]
        ancho, alto = monitor["width"], monitor["height"]
        pantallas.append({
            "numero": numero,
            "x": x,
            "y": y,
            "ancho": ancho,
            "alto": alto,
            "principal": x == 0 and y == 0,
            "con_cursor": (
                x <= cursor.x < x + ancho and y <= cursor.y < y + alto
            ),
        })
    return pantallas


def _fotografiar(region: tuple[int, int, int, int], destino: Path) -> tuple[int, int]:
    """Fotografía un rectángulo del escritorio y lo deja reducido en `destino`.

    Devuelve el tamaño final, que es el que ve el modelo. Va aparte de
    `_capturar_windows` para que las pruebas puedan comprobar qué rectángulo se
    pidió sin tener que mirar la pantalla de quien las ejecuta.
    """
    declarar_dpi()
    mss = _importar("mss", "mss")
    Image = _importar("PIL.Image", "Pillow")

    x, y, ancho, alto = region
    try:
        with mss.MSS() as sct:
            crudo = sct.grab(
                {"left": x, "top": y, "width": ancho, "height": alto}
            )
    except Exception as error:  # pragma: no cover - depende de la sesión
        raise ErrorPantalla(
            "Windows no me dejó fotografiar la pantalla. Suele pasar con la "
            "sesión bloqueada o por escritorio remoto."
        ) from error

    # `mss` entrega BGRA; el canal alfa no significa nada en una captura.
    imagen = Image.frombytes("RGB", crudo.size, crudo.bgra, "raw", "BGRX")
    final = _medida_reducida(imagen.width, imagen.height)
    if final != imagen.size:
        imagen = imagen.resize(final, Image.LANCZOS)
    imagen.save(destino, "JPEG", quality=CALIDAD_JPEG)
    return imagen.width, imagen.height


def _capturar_windows(selector: str, destino: Path) -> dict:
    pantallas = _pantallas_windows()
    if not pantallas:
        raise ErrorPantalla("Este ordenador no tiene ninguna pantalla activa")
    elegida = _elegir(pantallas, selector)

    if elegida is None:
        origen_x = min(p["x"] for p in pantallas)
        origen_y = min(p["y"] for p in pantallas)
        real_ancho = max(p["x"] + p["ancho"] for p in pantallas) - origen_x
        real_alto = max(p["y"] + p["alto"] for p in pantallas) - origen_y
        descrita, numero = "todas las pantallas", 0
    else:
        origen_x, origen_y = elegida["x"], elegida["y"]
        real_ancho, real_alto = elegida["ancho"], elegida["alto"]
        numero = elegida["numero"]
        descrita = (
            f"pantalla {numero} (principal)"
            if elegida["principal"]
            else f"pantalla {numero}"
        )

    ancho, alto = _fotografiar(
        (origen_x, origen_y, real_ancho, real_alto), destino
    )
    return {
        "pantalla": descrita,
        "numero": numero,
        "ancho": ancho,
        "alto": alto,
        "ancho_real": real_ancho,
        "alto_real": real_alto,
        # Donde empieza este rectángulo dentro del escritorio virtual. Sin esto
        # no se puede volver de un punto de la imagen a un punto de la pantalla:
        # el monitor de la izquierda tiene coordenadas negativas.
        "origen_x": origen_x,
        "origen_y": origen_y,
        "pantallas": len(pantallas),
    }


# ---------- macOS ----------

def _pantallas_mac() -> list[dict]:
    """La geometría de los monitores y dónde está el ratón, vía CoreGraphics.

    Se llama a la biblioteca del sistema con ctypes en vez de instalar PyObjC:
    son cuatro funciones y ninguna cambia nunca. `screencapture` sabe capturar
    un display por su número, pero no sabe decir cuál tiene el cursor, y eso es
    justo lo que hace falta aquí.
    """
    import ctypes  # noqa: PLC0415 - solo en macOS
    import ctypes.util  # noqa: PLC0415

    class _Punto(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    class _Tamano(ctypes.Structure):
        _fields_ = [("ancho", ctypes.c_double), ("alto", ctypes.c_double)]

    class _Rectangulo(ctypes.Structure):
        _fields_ = [("origen", _Punto), ("tamano", _Tamano)]

    ruta = ctypes.util.find_library("ApplicationServices")
    if not ruta:
        raise ErrorPantalla("No encuentro CoreGraphics en este Mac")
    marco = ctypes.CDLL(ruta)

    marco.CGGetActiveDisplayList.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    marco.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    marco.CGDisplayBounds.restype = _Rectangulo
    marco.CGMainDisplayID.restype = ctypes.c_uint32
    marco.CGEventCreate.argtypes = [ctypes.c_void_p]
    marco.CGEventCreate.restype = ctypes.c_void_p
    marco.CGEventGetLocation.argtypes = [ctypes.c_void_p]
    marco.CGEventGetLocation.restype = _Punto

    identificadores = (ctypes.c_uint32 * _MAXIMO_NUMERADO)()
    cuantos = ctypes.c_uint32()
    if marco.CGGetActiveDisplayList(
        _MAXIMO_NUMERADO, identificadores, ctypes.byref(cuantos)
    ) != 0:
        raise ErrorPantalla("No pude enumerar las pantallas de este Mac")

    evento = marco.CGEventCreate(None)
    raton = marco.CGEventGetLocation(evento)

    pantallas = []
    principal = marco.CGMainDisplayID()
    for indice in range(cuantos.value):
        identificador = identificadores[indice]
        limites = marco.CGDisplayBounds(identificador)
        x, y = limites.origen.x, limites.origen.y
        ancho, alto = limites.tamano.ancho, limites.tamano.alto
        pantallas.append(
            {
                # `screencapture -D` numera desde 1 en el orden de esta lista.
                "numero": indice + 1,
                "x": int(x),
                "y": int(y),
                "ancho": int(ancho),
                "alto": int(alto),
                "principal": identificador == principal,
                "con_cursor": (
                    x <= raton.x < x + ancho and y <= raton.y < y + alto
                ),
            }
        )
    return pantallas


def _elegir(pantallas: list[dict], selector: str) -> dict | None:
    """El monitor que toca, o None si lo pedido es «todas»."""
    if selector == "todas":
        return None

    if selector.startswith("n"):
        numero = int(selector[1:])
        elegida = next(
            (p for p in pantallas if p["numero"] == numero), None
        )
        if elegida is None:
            raise ErrorPantalla(
                f"Este ordenador solo tiene {len(pantallas)} pantalla(s) y me "
                f"has pedido la {numero}."
            )
        return elegida

    if selector == "secundaria":
        elegida = next((p for p in pantallas if not p["principal"]), None)
        if elegida is None:
            raise ErrorPantalla(
                "Este ordenador solo tiene una pantalla, así que no hay "
                "secundaria."
            )
        return elegida

    candidatas = {
        "cursor": lambda: next((p for p in pantallas if p["con_cursor"]), None),
        "principal": lambda: next((p for p in pantallas if p["principal"]), None),
        "izquierda": lambda: min(pantallas, key=lambda p: p["x"]),
        "derecha": lambda: max(pantallas, key=lambda p: p["x"]),
        "arriba": lambda: min(pantallas, key=lambda p: p["y"]),
        "abajo": lambda: max(pantallas, key=lambda p: p["y"]),
    }
    elegida = candidatas[selector]()
    # El ratón puede estar entre dos monitores mientras se mueve. La principal
    # es lo que habría mirado la persona.
    return elegida or next(p for p in pantallas if p["principal"])


def _capturar_mac(selector: str, destino: Path) -> dict:
    if not shutil.which("screencapture"):
        raise ErrorPantalla("Este Mac no tiene screencapture")

    pantallas = _pantallas_mac()
    if not pantallas:
        raise ErrorPantalla("Este ordenador no tiene ninguna pantalla activa")
    elegida = _elegir(pantallas, selector)

    # `-x` para que no suene el obturador: nadie ha pulsado nada.
    orden = ["screencapture", "-x", "-t", "jpg"]
    if elegida is not None:
        orden += ["-D", str(elegida["numero"])]
    orden.append(str(destino))

    completado = subprocess.run(
        orden,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=TIMEOUT_CAPTURA,
        stdin=subprocess.DEVNULL,
    )
    if completado.returncode != 0 or not destino.is_file():
        detalle = (completado.stderr or "").strip()
        raise ErrorPantalla(
            detalle[:300]
            or "macOS no me dejó capturar la pantalla. Comprueba el permiso de "
               "grabación de pantalla del agente en Ajustes del Sistema."
        )

    ancho, alto = _reducir_mac(destino)
    if elegida is None:
        origen_x = min(p["x"] for p in pantallas)
        origen_y = min(p["y"] for p in pantallas)
        virtual_ancho = max(p["x"] + p["ancho"] for p in pantallas) - origen_x
        virtual_alto = max(p["y"] + p["alto"] for p in pantallas) - origen_y
        return {
            "pantalla": "todas las pantallas",
            "numero": 0,
            "ancho": ancho,
            "alto": alto,
            "ancho_real": virtual_ancho,
            "alto_real": virtual_alto,
            "origen_x": origen_x,
            "origen_y": origen_y,
            "pantallas": len(pantallas),
        }
    return {
        "pantalla": (
            f"pantalla {elegida['numero']} (principal)"
            if elegida["principal"]
            else f"pantalla {elegida['numero']}"
        ),
        "numero": elegida["numero"],
        "ancho": ancho,
        "alto": alto,
        "ancho_real": elegida["ancho"],
        "alto_real": elegida["alto"],
        "origen_x": elegida["x"],
        "origen_y": elegida["y"],
        "pantallas": len(pantallas),
    }


def _reducir_mac(destino: Path) -> tuple[int, int]:
    """Encoge la captura con `sips` y devuelve el tamaño final."""
    subprocess.run(
        [
            "sips", "-Z", str(LADO_MAXIMO),
            "-s", "format", "jpeg",
            "-s", "formatOptions", str(CALIDAD_JPEG),
            str(destino),
        ],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_CAPTURA,
        stdin=subprocess.DEVNULL,
    )
    medidas = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(destino)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_CAPTURA,
        stdin=subprocess.DEVNULL,
    )
    ancho = alto = 0
    for linea in (medidas.stdout or "").splitlines():
        if "pixelWidth:" in linea:
            ancho = int(linea.split(":")[1].strip())
        elif "pixelHeight:" in linea:
            alto = int(linea.split(":")[1].strip())
    return ancho, alto


# ---------- El puente entre mirar y tocar ----------

# Qué se fotografió la última vez, en el formato que entiende `usecomputer`:
# `origenX,origenY,anchoReal,altoReal,anchoImagen,altoImagen`. Con esto, un
# punto de la imagen que vio el modelo se convierte en un punto del escritorio.
#
# Es estado global y lo es a conciencia: el modelo no puede llevar la cuenta de
# la geometría de un monitor que nunca ha visto, y obligarle a arrastrar seis
# números de una llamada a la siguiente es pedirle que se equivoque en uno. Se
# guarda el último y solo el último, que es lo que significa «ahí».
_ultimo_mapa: str = ""


def mapa_actual() -> str:
    """La traducción vigente de la imagen al escritorio, o vacío si no hay."""
    return _ultimo_mapa


def olvidar_mapa() -> None:
    """Tira la traducción. La usan las pruebas y quien pare el agente."""
    global _ultimo_mapa
    _ultimo_mapa = ""


def _recordar_mapa(detalle: dict) -> str:
    global _ultimo_mapa
    ancho, alto = detalle.get("ancho") or 0, detalle.get("alto") or 0
    if not ancho or not alto:
        return ""
    _ultimo_mapa = ",".join(
        str(int(valor))
        for valor in (
            detalle.get("origen_x") or 0,
            detalle.get("origen_y") or 0,
            detalle.get("ancho_real") or ancho,
            detalle.get("alto_real") or alto,
            ancho,
            alto,
        )
    )
    return _ultimo_mapa


# ---------- Entrada ----------

def capturar(pantalla: object = "") -> dict:
    """Fotografía una pantalla y devuelve el JPEG con lo que se ve en él.

    `pantalla` es lo que dijo la persona, tal cual: vacío significa aquella
    donde tenga el ratón, que es lo que quiere decir «mira mi pantalla» cuando
    hay dos.
    """
    selector = normalizar(pantalla)
    sistema = platform.system()
    if sistema not in ("Windows", "Darwin"):
        raise ErrorPantalla(
            f"Todavía no sé capturar la pantalla en {sistema or 'este sistema'}"
        )

    descriptor, ruta = tempfile.mkstemp(prefix="vibi-pantalla-", suffix=".jpg")
    os.close(descriptor)
    destino = Path(ruta)
    try:
        detalle = (
            _capturar_windows(selector, destino)
            if sistema == "Windows"
            else _capturar_mac(selector, destino)
        )
        imagen = destino.read_bytes()
    finally:
        destino.unlink(missing_ok=True)

    if not imagen:
        raise ErrorPantalla("La captura salió vacía")
    # Lo último que se miró es lo que se puede tocar: se apunta aquí para que
    # las acciones de `computer.py` sepan traducir lo que el modelo señale.
    _recordar_mapa(detalle)
    return {"jpeg": imagen, "detalle": {**detalle, "bytes": len(imagen)}}

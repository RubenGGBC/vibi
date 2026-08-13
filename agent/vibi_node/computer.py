"""El ratón y el teclado de esta máquina, pilotados por `usecomputer`.

`screen.py` ya sabe mirar la pantalla; esto es la otra mitad: tocarla. Detrás
está la CLI `usecomputer` (https://github.com/remorses/usecomputer), que habla
con las APIs de entrada de cada sistema —SendInput en Windows, CGEvent en
macOS, XTest en X11— y expone todo eso como comandos sueltos.

Se invoca como programa y no como librería a propósito. Es Node y aquí estamos
en Python, así que la alternativa sería un proceso servidor vivo con su
protocolo; para acciones que duran milisegundos y no guardan estado, arrancar el
binario cada vez sale más barato de mantener y no deja nada colgado si el agente
se muere a mitad.

**Las coordenadas son las de la captura, no las del escritorio.** Es la decisión
que hace que esto funcione. El modelo ve un JPEG de 1568 px de lado largo que
puede venir de un 4K, de la pantalla de la derecha o de las dos juntas; pedirle
que traduzca a coordenadas de escritorio es pedirle que multiplique a ojo y
acierte con el origen de un monitor que puede estar en negativo. Así que dice
dónde pinchar sobre lo que está viendo y la traducción la hace `usecomputer` con
el `--coord-map` que dejó la última captura (`screen.mapa_actual`).

Por eso, sin haber mirado antes no se puede tocar: es la disciplina de
screenshot → acción → screenshot, y aquí no es un consejo del prompt sino algo
que el código exige.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from . import screen
from .config import environment_value

# Cómo se llama el programa y el paquete que lo trae.
PROGRAMA = "usecomputer"
PAQUETE = "usecomputer@latest"

# Para decirle dónde está cuando no se pueda deducir. Mismo motivo que
# `VIBI_NPX` en `browser_mcp`: con nvm y compañía, el binario global de npm
# acaba en un directorio que nadie ha publicado en el PATH.
VARIABLE_BINARIO = "VIBI_USECOMPUTER"
LEGACY_VARIABLE_BINARIO = "MORGANA_USECOMPUTER"
VARIABLE_NPX = "VIBI_NPX"
LEGACY_VARIABLE_NPX = "MORGANA_NPX"

# Un clic tarda milisegundos; teclear un párrafo, unos segundos. El tope está
# para que un binario que se quede pensando no bloquee el agente, no para acotar
# una acción normal.
TIMEOUT = 60

# Teclear se hace por argumento hasta este tamaño y por stdin a partir de él.
# La CLI acepta las dos formas, pero una línea de comandos tiene techo en
# Windows (32.767 caracteres) y un texto largo con saltos de línea es
# exactamente lo que la revienta.
MAX_TEXTO_ARGUMENTO = 2_000

BOTONES = ("left", "right", "middle")
DIRECCIONES = ("up", "down", "left", "right")

# 0xC000001D, «instrucción ilegal»: el binario no ha fallado, se ha caído. Se
# compara en los dos signos porque quien lo cuenta cambia el signo: Python
# devuelve -1073741795 cuando lanza el ejecutable, y 3221225501 cuando lo que
# lanza es el `.cmd` que npm deja en Windows, porque ahí el código pasa por
# `cmd.exe` y llega sin signo.
CODIGO_INSTRUCCION_ILEGAL = 0xC000001D


def _se_ha_caido(codigo: int) -> bool:
    return (codigo & 0xFFFFFFFF) == CODIGO_INSTRUCCION_ILEGAL


# Ninguna espera se le pide a la CLI. Medido contra el binario de Windows
# 0.1.11: todo lo que hace `sleep` por dentro muere con instrucción ilegal, y
# los flags que la provocan son justo los que parecen inofensivos —`--count 1`
# tumba un `press` que sin él funciona, `--chunk-size` tumba un `--stdin` que
# sin él funciona—. Así que las repeticiones se cuentan aquí, invocando la CLI
# una vez por pulsación, y los retardos no se ofrecen: no son necesarios para
# nada y son la forma más fácil de tirar una acción que iba a funcionar.



class ErrorOrdenador(Exception):
    pass


def _npm_global() -> Path | None:
    """Donde npm deja los binarios globales, que no siempre está en el PATH.

    En Windows es `%APPDATA%\\npm` y el instalador no lo publica siempre; en
    Unix es el `bin` del prefijo, y ahí sí suele estar. Se mira antes de
    rendirse a `npx`, que cuesta un par de segundos por invocación.
    """
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "").strip()
        return Path(appdata) / "npm" if appdata else None
    node = shutil.which("node")
    return Path(node).parent if node else None


def _npx() -> str | None:
    declarado = environment_value(VARIABLE_NPX, LEGACY_VARIABLE_NPX).strip()
    if declarado and Path(declarado).exists():
        return declarado
    ruta = shutil.which("npx")
    if ruta:
        return ruta
    node = shutil.which("node")
    if node:
        return shutil.which("npx", path=str(Path(node).parent))
    return None


def argv_base() -> list[str]:
    """Con qué se invoca la CLI. Aparte para poder comprobarlo en un test.

    El orden es por coste: lo instalado gana a `npx`, que en cada llamada
    comprueba el registro y puede acabar descargando el paquete entero.
    """
    declarado = environment_value(VARIABLE_BINARIO, LEGACY_VARIABLE_BINARIO).strip()
    if declarado:
        if not Path(declarado).exists():
            raise ErrorOrdenador(
                f"{VARIABLE_BINARIO} apunta a {declarado}, que no existe"
            )
        return [declarado]

    # `which` resuelve `usecomputer.cmd` en Windows mirando PATHEXT, cosa que
    # `Popen` sin shell no hace por su cuenta.
    ruta = shutil.which(PROGRAMA)
    if ruta:
        return [ruta]

    global_npm = _npm_global()
    if global_npm is not None:
        vecino = shutil.which(PROGRAMA, path=str(global_npm))
        if vecino:
            return [vecino]

    npx = _npx()
    if npx:
        return [npx, "--yes", PAQUETE]

    raise ErrorOrdenador(
        f"No encuentro {PROGRAMA} en este ordenador. Instálalo con "
        f"«npm install -g {PROGRAMA}» y vuelve a intentarlo; si ya está "
        f"puesto pero fuera del PATH, apunta {VARIABLE_BINARIO} a su "
        f"ejecutable."
    )


def disponible() -> bool:
    try:
        argv_base()
    except ErrorOrdenador:
        return False
    return True


def _motivo(completado: subprocess.CompletedProcess) -> str:
    """Traduce el fallo de la CLI a algo que se pueda leer en un chat."""
    if _se_ha_caido(completado.returncode):
        # No es un error suyo: el proceso se ha caído. El binario de Windows
        # publicado en 0.1.11 tumba con instrucción ilegal todo lo que mueve el
        # puntero —clic, arrastrar, rueda, colocar el ratón— y el listado de
        # ventanas. El teclado funciona, y por eso el mensaje lo dice: quien lo
        # lea puede seguir por otro camino en vez de darse por vencido.
        return (
            "usecomputer se ha caído al ejecutar la acción (instrucción "
            "ilegal). Es un fallo del binario, no del ordenador: en Windows la "
            "versión 0.1.11 tumba todo lo que mueve el ratón —clic, arrastrar, "
            "rueda— mientras que el teclado (escribir y pulsar teclas) sí "
            "funciona. Si puedes hacerlo con el teclado, hazlo; si no, hay que "
            f"actualizar la CLI: «npm install -g {PROGRAMA}»."
        )

    detalle = (completado.stderr or completado.stdout or "").strip()
    primera = next(
        (linea.strip() for linea in detalle.splitlines() if linea.strip()), ""
    )
    # La CLI escribe «error: UnknownKey (EVENT_POST_FAILED)». El código entre
    # paréntesis no le dice nada a nadie fuera de su código fuente.
    if primera.startswith("error: "):
        primera = primera[len("error: "):]
    codigo, _, _ = primera.partition(" (")
    conocidos = {
        "UnknownKey": (
            "Esa tecla no la conoce. Usa nombres como «enter», «tab», "
            "«escape», «up», «f5» o combinaciones con «+»."
        ),
        "MissingMainKey": (
            "Has pasado solo modificadores. Una combinación necesita una "
            "tecla de verdad detrás: «ctrl+s», no «ctrl»."
        ),
        "InvalidInput": "La CLI no ha entendido los argumentos.",
        "UnsupportedPlatform": (
            "usecomputer no sabe hacer esto en este sistema operativo."
        ),
    }
    if codigo in conocidos:
        return conocidos[codigo]
    return primera[:300] or f"usecomputer falló con código {completado.returncode}"


def _ejecutar(argumentos: list[str], entrada: str | None = None) -> str:
    argv = [*argv_base(), *argumentos]
    try:
        completado = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
            input=entrada,
            stdin=None if entrada is not None else subprocess.DEVNULL,
        )
    except FileNotFoundError as error:
        raise ErrorOrdenador(
            f"No pude ejecutar {PROGRAMA}: {error}"
        ) from error
    except subprocess.TimeoutExpired as expirado:
        raise ErrorOrdenador(
            f"La acción no terminó en {TIMEOUT}s y se ha cortado"
        ) from expirado

    if completado.returncode != 0:
        raise ErrorOrdenador(_motivo(completado))
    return completado.stdout or ""


def _json(argumentos: list[str]) -> object:
    salida = _ejecutar([*argumentos, "--json"]).strip()
    try:
        return json.loads(salida or "null")
    except ValueError as error:
        raise ErrorOrdenador(
            "usecomputer contestó algo que no es JSON"
        ) from error


# ---------- Coordenadas ----------

def _mapa() -> str:
    """El `--coord-map` de la última captura, o el aviso de que falta una.

    Sin captura previa no hay traducción posible, y adivinar sería pinchar en
    un sitio cualquiera de una pantalla que no hemos visto.
    """
    mapa = screen.mapa_actual()
    if not mapa:
        raise ErrorOrdenador(
            "No sé sobre qué pantalla estás señalando: mira primero la "
            "pantalla y después dime dónde pinchar, con las coordenadas de "
            "la imagen que has visto."
        )
    return mapa


def _punto(x: object, y: object) -> tuple[int, int]:
    try:
        return int(round(float(x))), int(round(float(y)))
    except (TypeError, ValueError):
        raise ErrorOrdenador(
            f"Las coordenadas tienen que ser números, y me has dado "
            f"«{x}, {y}»"
        ) from None


def _entero(valor: object, nombre: str, minimo: int, maximo: int) -> int:
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ErrorOrdenador(f"{nombre} tiene que ser un número") from None
    return max(minimo, min(numero, maximo))


# ---------- Acciones ----------

def clic(
    x: object,
    y: object,
    boton: str = "left",
    veces: object = 1,
    modificadores: tuple[str, ...] = (),
) -> dict:
    """Pincha en un punto de la última captura."""
    boton = (boton or "left").strip().lower()
    if boton not in BOTONES:
        raise ErrorOrdenador(
            f"«{boton}» no es un botón: usa left, right o middle"
        )
    columna, fila = _punto(x, y)
    argumentos = [
        "click",
        "-x", str(columna),
        "-y", str(fila),
        "--button", boton,
        "--coord-map", _mapa(),
    ]
    repeticiones = _entero(veces, "El número de clics", 1, 3)
    if repeticiones > 1:
        # Aquí sí va a la CLI: dos invocaciones seguidas llegarían demasiado
        # separadas y el sistema las contaría como dos clics sueltos, no como
        # un doble clic.
        argumentos += ["--count", str(repeticiones)]
    for modificador in modificadores:
        limpio = str(modificador).strip().lower()
        if limpio:
            argumentos += ["--modifier", limpio]
    _ejecutar(argumentos)
    return {"accion": "clic", "x": columna, "y": fila, "boton": boton}


def clic_escritorio(
    x: object,
    y: object,
    boton: str = "left",
    veces: object = 1,
) -> dict:
    """Pincha en coordenadas de escritorio, sin pasar por ninguna captura.

    Lo usa el árbol de accesibilidad (`ui_windows`, `ui_macos`), que sabe
    exactamente dónde está cada elemento porque el sistema se lo ha dicho en
    píxeles de verdad. Aquí no hay nada que traducir, y por eso no se pide el
    `--coord-map` que `clic` sí exige: pedirlo obligaría a haber hecho una
    captura antes para poder pulsar algo que ya tenemos localizado.

    Es la salida de emergencia del árbol, no su camino normal. Casi todo se
    pulsa por su patrón de UIA, que no depende de dónde esté la ventana ni de
    que nada la tape; esto queda para lo que no expone patrón y para el clic
    derecho, que no tiene equivalente.
    """
    boton = (boton or "left").strip().lower()
    if boton not in BOTONES:
        raise ErrorOrdenador(
            f"«{boton}» no es un botón: usa left, right o middle"
        )
    columna, fila = _punto(x, y)
    argumentos = ["click", "-x", str(columna), "-y", str(fila), "--button", boton]
    repeticiones = _entero(veces, "El número de clics", 1, 3)
    if repeticiones > 1:
        argumentos += ["--count", str(repeticiones)]
    _ejecutar(argumentos)
    return {"accion": "clic", "x": columna, "y": fila, "boton": boton}


def mover(x: object, y: object) -> dict:
    """Lleva el puntero a un punto sin pulsar nada.

    Sirve para lo que solo aparece al pasar por encima: un menú que se
    despliega, un tooltip, un botón que solo se ve con el ratón dentro.
    """
    columna, fila = _punto(x, y)
    _ejecutar(
        ["hover", "-x", str(columna), "-y", str(fila), "--coord-map", _mapa()]
    )
    return {"accion": "mover", "x": columna, "y": fila}


def arrastrar(
    desde_x: object,
    desde_y: object,
    hasta_x: object,
    hasta_y: object,
    boton: str = "left",
) -> dict:
    """Arrastra de un punto a otro con el botón pulsado."""
    boton = (boton or "left").strip().lower()
    if boton not in BOTONES:
        raise ErrorOrdenador(
            f"«{boton}» no es un botón: usa left, right o middle"
        )
    origen = _punto(desde_x, desde_y)
    destino = _punto(hasta_x, hasta_y)
    _ejecutar(
        [
            "drag",
            f"{origen[0]},{origen[1]}",
            f"{destino[0]},{destino[1]}",
            "--button", boton,
            "--coord-map", _mapa(),
        ]
    )
    return {"accion": "arrastrar", "desde": origen, "hasta": destino}


def desplazar(direccion: str, cantidad: object = 3, en: tuple | None = None) -> dict:
    """Gira la rueda. `en` es dónde ponerse antes, si importa la ventana."""
    direccion = (direccion or "").strip().lower()
    if direccion not in DIRECCIONES:
        raise ErrorOrdenador(
            f"«{direccion}» no es una dirección: usa up, down, left o right"
        )
    pasos = _entero(cantidad if cantidad is not None else 3, "La cantidad", 1, 50)
    argumentos = ["scroll", direccion, str(pasos)]
    if en:
        columna, fila = _punto(en[0], en[1])
        # `--at` no admite `--coord-map`, así que el punto se traduce aquí.
        argumentos += ["--at", f"{_traducir(columna, fila)}"]
    _ejecutar(argumentos)
    return {"accion": "desplazar", "direccion": direccion, "cantidad": pasos}


def _traducir(x: int, y: int) -> str:
    """De coordenadas de la captura a coordenadas de escritorio.

    Lo normal es dejarle esto a `--coord-map`, pero `scroll --at` no lo acepta
    y hay que hacer la misma cuenta a mano. El mapa es
    `origenX,origenY,anchoReal,altoReal,anchoImagen,altoImagen`.
    """
    partes = _mapa().split(",")
    if len(partes) != 6:
        raise ErrorOrdenador("El mapa de la última captura está corrupto")
    origen_x, origen_y, ancho, alto, ancho_imagen, alto_imagen = (
        float(parte) for parte in partes
    )
    if not ancho_imagen or not alto_imagen:
        raise ErrorOrdenador("El mapa de la última captura está corrupto")
    return (
        f"{round(origen_x + x * ancho / ancho_imagen)},"
        f"{round(origen_y + y * alto / alto_imagen)}"
    )


def teclear(texto: str) -> dict:
    """Escribe texto como si lo tecleara una persona, donde esté el foco."""
    texto = str(texto or "")
    if not texto:
        raise ErrorOrdenador("No has dicho qué escribir")

    if len(texto) > MAX_TEXTO_ARGUMENTO:
        _ejecutar(["type", "--stdin"], entrada=texto)
    else:
        _ejecutar(["type", texto])
    return {"accion": "teclear", "caracteres": len(texto)}


def pulsar(tecla: str, veces: object = 1) -> dict:
    """Pulsa una tecla o una combinación: «enter», «ctrl+s», «alt+tab».

    Repetir se hace desde aquí, una invocación por pulsación. Es más lento que
    `--count` y es lo que hay: ese flag se lleva por delante el binario de
    Windows, y bajar diez líneas es exactamente lo que se quiere poder hacer.
    """
    tecla = str(tecla or "").strip()
    if not tecla:
        raise ErrorOrdenador("No has dicho qué tecla pulsar")
    repeticiones = _entero(veces, "Las repeticiones", 1, 50)
    for _ in range(repeticiones):
        _ejecutar(["press", tecla])
    return {"accion": "pulsar", "tecla": tecla, "veces": repeticiones}


# ---------- Consultas ----------

def raton() -> dict:
    """Dónde está el puntero, en coordenadas de escritorio."""
    posicion = _json(["mouse", "position"])
    if not isinstance(posicion, dict):
        raise ErrorOrdenador("usecomputer no dijo dónde está el ratón")
    return posicion


def ventanas() -> list:
    """Las ventanas abiertas, con su título y su sitio."""
    lista = _json(["window", "list"])
    return lista if isinstance(lista, list) else []


def pantallas() -> list:
    """Los monitores conectados, tal como los ve usecomputer."""
    lista = _json(["display", "list"])
    return lista if isinstance(lista, list) else []

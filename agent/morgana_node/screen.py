"""Lo que se ve ahora mismo en las pantallas de esta máquina.

Captura con lo que ya trae el sistema y no con una librería: en Windows,
`System.Windows.Forms` y `System.Drawing` a través de PowerShell; en macOS,
`screencapture` y `sips`, que vienen puestos. El agente se instala con cuatro
dependencias y la idea es que siga siendo así, porque quien lo instala es el
usuario en su propio ordenador y cada paquete nuevo es una forma más de que la
instalación falle en una máquina y no en otra.

El reparto entre Python y el script nativo es deliberado: **entender qué
pantalla te han pedido se hace aquí, medirla y fotografiarla se hace allí.**
Traducir «la de la derecha» a un monitor es la parte que no cambia entre
sistemas, y tenerla dos veces era garantizar que un día dijeran cosas distintas.
La geometría, en cambio, solo la sabe cada sistema operativo.

La imagen sale ya reducida y en JPEG. Un 4K en PNG son ocho megas que ningún
modelo va a mirar a esa resolución: se recorta el lado largo a 1568 px, que es
lo que aprovecha la API, y el resto es peso que solo serviría para pagar
transferencia.
"""
from __future__ import annotations

import json
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

# Arrancar PowerShell y cargar WinForms no es instantáneo, y encima hay que
# compilar el trocito de C# que pide el DPI real. Con margen para una máquina
# cargada.
TIMEOUT_CAPTURA = 45


class ErrorPantalla(Exception):
    pass


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

_POWERSHELL = r"""
param(
    [string]$Selector = "cursor",
    [string]$Destino,
    [int]$LadoMaximo = 1568,
    [int]$Calidad = 80
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Sin esto Windows le miente al proceso sobre el tamano de las pantallas con
# escalado: cada monitor se describe en sus coordenadas virtuales y con dos
# escalados distintos los rectangulos dejan de encajar, asi que la captura de
# uno se lleva un trozo del otro. Compilar esta linea cuesta cerca de un
# segundo la primera vez de cada proceso; es el precio de que las coordenadas
# sean las de verdad.
Add-Type @"
using System.Runtime.InteropServices;
public static class MorganaDpi {
    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();
}
"@
[void][MorganaDpi]::SetProcessDPIAware()

$pantallas = [System.Windows.Forms.Screen]::AllScreens
$cursor = [System.Windows.Forms.Cursor]::Position

$lista = @()
for ($i = 0; $i -lt $pantallas.Length; $i++) {
    $limites = $pantallas[$i].Bounds
    $lista += [pscustomobject]@{
        numero     = $i + 1
        x          = $limites.X
        y          = $limites.Y
        ancho      = $limites.Width
        alto       = $limites.Height
        principal  = [bool]$pantallas[$i].Primary
        con_cursor = $limites.Contains($cursor)
    }
}

$virtual = [System.Windows.Forms.SystemInformation]::VirtualScreen
$elegida = $null
$todas = $false

switch -Regex ($Selector) {
    "^cursor$"     { $elegida = $lista | Where-Object { $_.con_cursor } | Select-Object -First 1 }
    "^principal$"  { $elegida = $lista | Where-Object { $_.principal } | Select-Object -First 1 }
    "^secundaria$" { $elegida = $lista | Where-Object { -not $_.principal } | Select-Object -First 1 }
    "^izquierda$"  { $elegida = $lista | Sort-Object x | Select-Object -First 1 }
    "^derecha$"    { $elegida = $lista | Sort-Object x -Descending | Select-Object -First 1 }
    "^arriba$"     { $elegida = $lista | Sort-Object y | Select-Object -First 1 }
    "^abajo$"      { $elegida = $lista | Sort-Object y -Descending | Select-Object -First 1 }
    "^todas$"      { $todas = $true }
    "^n(\d+)$"     { $elegida = $lista | Where-Object { $_.numero -eq [int]$Matches[1] } | Select-Object -First 1 }
}

# El raton puede estar fuera de todo rectangulo mientras se mueve entre
# monitores, y una pantalla que no existe es lo normal cuando pides la
# secundaria de un portatil suelto. En ambos casos vale la principal: es la que
# habria mirado la persona.
if (-not $todas -and $null -eq $elegida) {
    if ($Selector -match "^n(\d+)$" -or $Selector -eq "secundaria") {
        $disponibles = ($lista | Measure-Object).Count
        # Una marca, no una frase. Este archivo se escribe en ASCII para no
        # depender de como interprete PowerShell su codificacion, y la frase que
        # va a leer una persona lleva tildes: se compone en Python.
        [Console]::Error.WriteLine("MORGANA_POCAS_PANTALLAS $disponibles")
        exit 1
    }
    $elegida = $lista | Where-Object { $_.principal } | Select-Object -First 1
}

if ($todas) {
    $x = $virtual.X; $y = $virtual.Y
    $ancho = $virtual.Width; $alto = $virtual.Height
    $descrita = "todas las pantallas"
    $numero = 0
} else {
    $x = $elegida.x; $y = $elegida.y
    $ancho = $elegida.ancho; $alto = $elegida.alto
    $descrita = if ($elegida.principal) { "pantalla $($elegida.numero) (principal)" } else { "pantalla $($elegida.numero)" }
    $numero = $elegida.numero
}

$lienzo = New-Object System.Drawing.Bitmap($ancho, $alto, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$pincel = [System.Drawing.Graphics]::FromImage($lienzo)
$pincel.CopyFromScreen($x, $y, 0, 0, (New-Object System.Drawing.Size($ancho, $alto)), [System.Drawing.CopyPixelOperation]::SourceCopy)
$pincel.Dispose()

$escala = [Math]::Min(1.0, $LadoMaximo / [double][Math]::Max($ancho, $alto))
$final = $lienzo
if ($escala -lt 1.0) {
    $nuevoAncho = [Math]::Max(1, [int][Math]::Round($ancho * $escala))
    $nuevoAlto = [Math]::Max(1, [int][Math]::Round($alto * $escala))
    $final = New-Object System.Drawing.Bitmap($nuevoAncho, $nuevoAlto)
    $reductor = [System.Drawing.Graphics]::FromImage($final)
    $reductor.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $reductor.DrawImage($lienzo, 0, 0, $nuevoAncho, $nuevoAlto)
    $reductor.Dispose()
    $lienzo.Dispose()
}

$codificador = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() |
    Where-Object { $_.MimeType -eq "image/jpeg" } | Select-Object -First 1
$ajustes = New-Object System.Drawing.Imaging.EncoderParameters(1)
$ajustes.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter(
    [System.Drawing.Imaging.Encoder]::Quality, [long]$Calidad)
$final.Save($Destino, $codificador, $ajustes)
$anchoFinal = $final.Width
$altoFinal = $final.Height
$final.Dispose()

$salida = @{
    pantalla   = $descrita
    numero     = $numero
    ancho      = $anchoFinal
    alto       = $altoFinal
    ancho_real = $ancho
    alto_real  = $alto
    # Donde empieza este rectangulo dentro del escritorio virtual. Sin esto no
    # se puede volver de un punto de la imagen a un punto de la pantalla: el
    # monitor de la izquierda tiene coordenadas negativas.
    origen_x   = $x
    origen_y   = $y
    pantallas  = ($lista | Measure-Object).Count
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output ($salida | ConvertTo-Json -Compress)
"""


def _capturar_windows(selector: str, destino: Path) -> dict:
    guion = destino.with_suffix(".ps1")
    guion.write_text(_POWERSHELL, encoding="utf-8")
    try:
        completado = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(guion),
                "-Selector",
                selector,
                "-Destino",
                str(destino),
                "-LadoMaximo",
                str(LADO_MAXIMO),
                "-Calidad",
                str(CALIDAD_JPEG),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT_CAPTURA,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as expirado:
        raise ErrorPantalla(
            f"La captura no terminó en {TIMEOUT_CAPTURA}s"
        ) from expirado
    finally:
        guion.unlink(missing_ok=True)

    if completado.returncode != 0:
        detalle = (completado.stderr or completado.stdout or "").strip()
        raise ErrorPantalla(
            _motivo_windows(detalle) or "No pude capturar la pantalla"
        )

    try:
        return json.loads(completado.stdout.strip() or "{}")
    except ValueError as error:
        raise ErrorPantalla(
            "La captura terminó pero no entendí lo que devolvió el sistema"
        ) from error


def _motivo_windows(detalle: str) -> str:
    """Convierte el vómito de PowerShell en algo que se pueda leer en un chat."""
    if not detalle:
        return ""
    # PowerShell escribe el error, la línea del script, el subrayado con
    # tildes y la categoría. Solo la primera línea dice algo, y encima viene
    # con la ruta del script pegada delante («C:\...\x.ps1 : de verdad falló»).
    primera = next(
        (linea.strip() for linea in detalle.splitlines() if linea.strip()), ""
    )
    cabecera, separador, resto = primera.partition(" : ")
    if separador and cabecera.casefold().endswith(".ps1"):
        primera = resto.strip()

    marca, _, cuantas = primera.partition(" ")
    if marca == "MORGANA_POCAS_PANTALLAS":
        cuantas = cuantas.strip() or "1"
        plural = "s" if cuantas != "1" else ""
        return (
            f"Este ordenador solo tiene {cuantas} pantalla{plural}, así que no "
            f"puedo enseñarte la que me pides."
        )

    if "CopyFromScreen" in detalle or "GDI+" in detalle:
        return (
            "Windows no me dejó fotografiar la pantalla. Suele pasar con la "
            "sesión bloqueada o por escritorio remoto."
        )
    return primera[:300]


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

    descriptor, ruta = tempfile.mkstemp(prefix="morgana-pantalla-", suffix=".jpg")
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

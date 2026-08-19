"""Lo que el instalador cambia de verdad en la máquina.

Separado de `deteccion` porque son dos trabajos distintos: allí se mira y se
decide, aquí se toca. Todo lo que hay aquí tiene que poder repetirse sin
estropear una instalación que ya funcionaba, porque reinstalar es lo normal
—se actualiza el repo y se vuelve a lanzar— y quien reinstala ya tiene sus
claves puestas.

**Solo biblioteca estándar**: esto corre antes de que exista el entorno.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

NOMBRE_ENTORNO = ".venv-host"

# Lo que el asistente pregunta y, por tanto, lo único que puede sobrescribir.
# Todo lo demás que hubiera en el `.env` se conserva tal cual: son claves de
# servicios de terceros y ajustes que el usuario tocó a mano, y perderlos al
# reinstalar es la forma más rápida de que no vuelva a lanzar el instalador.
#
# El motor NO está aquí, y es importante: se guarda por usuario en la tabla
# `user_ai_settings`, no en el `.env`. Escribir `CHAT_PROVIDER` ahí no rompe el
# instalador —rompe el arranque del core entero, porque `Settings` prohíbe los
# campos que no conoce— y con un error de pydantic que no menciona ni al
# `.env` ni al instalador. Lo pone `crear_usuario`, que ya corre con las
# dependencias instaladas y puede hablar con la base de datos.
CLAVES_QUE_PREGUNTAMOS = (
    "ANTIGRAVITY_MODEL",
    "ANTIGRAVITY_EFFORT",
    "PLAYWRIGHT_MCP_ENABLED",
    "SYSTEM_MCP_ENABLED",
)


def leer_env(ruta: Path) -> dict[str, str]:
    """Lo que ya hubiera en un `.env`, sin comentarios ni líneas vacías.

    Se parte por el primer `=` y no por todos: los secretos en base64 acaban en
    `=` de relleno y partirlos por la mitad deja al usuario con una clave
    truncada que falla en el primer turno.
    """
    valores: dict[str, str] = {}
    try:
        crudo = ruta.read_text(encoding="utf-8")
    except OSError:
        return valores
    for linea in crudo.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        clave, _, valor = limpia.partition("=")
        valores[clave.strip()] = valor.strip()
    return valores


def valor_de(contenido: str, clave: str) -> str:
    """El valor de una clave dentro de un `.env` ya compuesto. Para las pruebas."""
    for linea in contenido.splitlines():
        limpia = linea.strip()
        if limpia.startswith(f"{clave}="):
            return limpia.partition("=")[2].strip()
    return ""


def contenido_env(previo: dict[str, str], eleccion: dict) -> str:
    """El `.env` que se va a escribir: lo elegido encima de lo que ya había.

    El `JWT_SECRET` merece un párrafo: con él se firman las sesiones. Si se
    inventa uno nuevo en cada reinstalación, todos los dispositivos ya
    emparejados —el móvil, el companion, Telegram— se quedan fuera sin que
    nadie entienda por qué. Se conserva siempre que exista.
    """
    capacidades = dict(eleccion.get("capacidades") or {})
    valores = dict(previo)
    valores.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
    if eleccion.get("modelo"):
        valores["ANTIGRAVITY_MODEL"] = eleccion["modelo"]
    if eleccion.get("effort"):
        valores["ANTIGRAVITY_EFFORT"] = eleccion["effort"]
    if "navegador" in capacidades:
        valores["PLAYWRIGHT_MCP_ENABLED"] = (
            "true" if capacidades["navegador"] else "false"
        )
    if "terminal" in capacidades:
        # El servidor MCP del disco solo se declara cuando el disco está en
        # otra máquina; aquí manda si el nodo lo sirve siquiera.
        valores["SYSTEM_MCP_ENABLED"] = "true" if capacidades["terminal"] else "false"

    cabecera = (
        "# Configuración de Vibi.\n"
        "#\n"
        "# La escribió el instalador, pero es tuya: puedes editarla a mano y\n"
        "# volver a lanzarlo sin miedo, que solo toca lo que te pregunta.\n"
        "# Todo lo demás que pongas aquí se conserva.\n"
    )
    lineas = [f"{clave}={valor}" for clave, valor in sorted(valores.items())]
    return cabecera + "\n".join(lineas) + "\n"


def escribir_env(raiz: Path, eleccion: dict) -> Path:
    ruta = raiz / ".env"
    contenido = contenido_env(leer_env(ruta), eleccion)
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def python_del_entorno(raiz: Path) -> Path:
    """El intérprete del entorno propio de Vibi, en cada sistema."""
    if sys.platform == "win32":
        return raiz / NOMBRE_ENTORNO / "Scripts" / "python.exe"
    return raiz / NOMBRE_ENTORNO / "bin" / "python"


def crear_entorno(raiz: Path) -> Path:
    """Un entorno propio, para no ensuciar el Python del sistema.

    Se reaprovecha si ya está: crear el entorno es de lo más lento del
    instalador y quien reinstala no tiene por qué pagarlo otra vez.
    """
    destino = python_del_entorno(raiz)
    if destino.exists():
        return destino
    subprocess.run(
        [sys.executable, "-m", "venv", str(raiz / NOMBRE_ENTORNO)],
        check=True,
        capture_output=True,
    )
    return destino


def guion_de_arranque(so: str, raiz: Path) -> str:
    """Dónde vive el guion que deja Vibi en marcha en este sistema."""
    if so == "windows":
        return str(raiz / "scripts" / "vibi.cmd")
    return str(raiz / "scripts" / "vibi.sh")


GUION_UNIX = """#!/usr/bin/env bash
# Deja Vibi en marcha: el core y el agente de nodo, cada uno con su bucle.
#
# Los dos van en la misma máquina a proposito. `agy` se lanza donde se lanza el
# core, y teniendolo aqui sus herramientas propias son tu disco de verdad.
set -uo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGDIR="${XDG_STATE_HOME:-$HOME/.local/state}/vibi"
mkdir -p "$LOGDIR"
PY="$RAIZ/.venv-host/bin/python"

if [ ! -x "$PY" ]; then
  echo "Falta $PY. Lanza el instalador otra vez." >&2
  exit 1
fi

# Un bucle por proceso: si uno muere, vuelve solo sin llevarse al otro.
bucle() {
  local nombre="$1"; shift
  while true; do
    echo "[$(date -Is)] arrancando $nombre" >> "$LOGDIR/$nombre.log"
    "$@" >> "$LOGDIR/$nombre.log" 2>&1
    echo "[$(date -Is)] $nombre termino; reintento en 15s" >> "$LOGDIR/$nombre.log"
    sleep 15
  done
}

cd "$RAIZ" || exit 1
bucle core "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
cd "$RAIZ/agent" || exit 1
bucle nodo "$PY" -m vibi_node &

# La ventana va con los servicios: Vibi es una aplicacion, y arrancar solo el
# core dejaba al usuario con todo corriendo y nada que mirar.
APP="$HOME/.local/bin/vibi-companion"
[ -x "$APP" ] && "$APP" >/dev/null 2>&1 &

wait
"""


def escribir_arranque(so: str, raiz: Path) -> str:
    """Deja el guion que mantiene Vibi viva, y lo hace ejecutable en Unix."""
    destino = Path(guion_de_arranque(so, raiz))
    destino.parent.mkdir(parents=True, exist_ok=True)
    if so == "windows":
        # En Windows ya existen `core.cmd` y `agente-nodo.cmd`, cada uno con su
        # bucle: este solo los encadena para no duplicar la lógica.
        destino.write_text(GUION_WINDOWS, encoding="utf-8")
        # Y su envoltorio silencioso, que es por donde se arranca de verdad.
        (destino.parent / "vibi.vbs").write_text(
            GUION_WINDOWS_VBS, encoding="utf-8"
        )
    else:
        destino.write_text(GUION_UNIX, encoding="utf-8")
        destino.chmod(destino.stat().st_mode | 0o111)
    return str(destino)


# Delimitado con comillas simples a propósito: el VBScript de dentro escapa sus
# comillas duplicándolas (`""""`), y eso cerraría un triple-comilla-doble de
# Python a mitad de línea.
GUION_WINDOWS_VBS = '''' Arranca Vibi sin dejar ventanas negras por el escritorio.
'
' Mismo motivo que core.vbs y agente-nodo.vbs: el 0 del Run la oculta y el
' False no espera, que es lo que quieres de algo que se queda vivo.
Dim shell, carpeta
Set shell = CreateObject("WScript.Shell")
carpeta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\\"))
shell.Run """" & carpeta & "vibi.cmd""", 0, False
'''

GUION_WINDOWS = """@echo off
rem Deja Vibi en marcha: el core, el agente de nodo y su ventana.
rem
rem Los dos primeros traen su propio bucle de reintento, asi que aqui solo se
rem lanzan. Van ocultos por los .vbs para no dejar ventanas negras abiertas.
rem
rem La ventana va con ellos a proposito: Vibi es una aplicacion, y arrancar solo
rem los servicios dejaba al usuario con todo corriendo y nada que mirar.
setlocal
set "AQUI=%~dp0"
start "" wscript.exe "%AQUI%core.vbs"
start "" wscript.exe "%AQUI%agente-nodo.vbs"
if exist "%LOCALAPPDATA%\Vibiibi-companion.exe" (
    start "" "%LOCALAPPDATA%\Vibiibi-companion.exe"
)
"""


def _sondear(url: str) -> int:
    """El código que devuelve Vibi, o revienta si todavía no escucha."""
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    try:
        with urllib.request.urlopen(url, timeout=4) as respuesta:
            return respuesta.status
    except urllib.error.HTTPError as error:
        # Un 401 es una respuesta como otra cualquiera: prueba que está
        # sirviendo. Solo faltaba la credencial, que aquí no viene al caso.
        return error.code


def esperar_a_vibi(
    url: str, segundos: float, sondear=_sondear, pausa: float = 0.5
) -> bool:
    """Espera a que Vibi conteste de verdad. Devuelve si lo consiguió.

    Lanzar el proceso no es que esté lista: el core tarda unos segundos en
    abrir el puerto, y darla por buena antes manda al usuario a una página que
    no carga justo cuando acaba de instalar. Cualquier respuesta HTTP vale
    —incluido el 401 de no traer credenciales—: lo que se comprueba es que hay
    alguien escuchando.
    """
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            if sondear(url):
                return True
        except Exception:  # noqa: BLE001 - aún no escucha, se reintenta
            pass
        if pausa:
            time.sleep(pausa)
    return False


def donde_esta_la_app() -> str:
    """La ventana de Vibi, donde la deja su propio instalador.

    Es lo que se abre al terminar: una aplicación no lanza el navegador. Que
    devuelva vacío es información, no un fallo — significa que hay core pero
    todavía no hay app, y eso hay que decirlo en vez de disimularlo abriendo
    una pestaña.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        candidato = base / "Vibi" / "vibi-companion.exe"
    elif sys.platform == "darwin":
        candidato = Path("/Applications/Vibi.app/Contents/MacOS/vibi-companion")
    else:
        candidato = Path.home() / ".local" / "bin" / "vibi-companion"
    return str(candidato) if candidato.is_file() else ""


def abrir_app() -> bool:
    """Abre la ventana de Vibi. Devuelve si había algo que abrir."""
    app = donde_esta_la_app()
    if not app:
        return False
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", app])
    else:
        subprocess.Popen([app], cwd=str(Path(app).parent))
    return True


def arrancar_vibi(so: str, raiz: Path) -> None:
    """Deja Vibi en marcha, sin atarla a la vida del instalador.

    En Windows va por el `.vbs`, que la abre sin dejar dos ventanas negras por
    el escritorio. Fuera, en segundo plano y con su propia sesión, para que
    cerrar el instalador no se la lleve por delante.
    """
    if so == "windows":
        subprocess.Popen(
            ["wscript.exe", str(raiz / "scripts" / "vibi.vbs")],
            cwd=str(raiz),
        )
        return
    subprocess.Popen(
        ["bash", guion_de_arranque(so, raiz)],
        cwd=str(raiz),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def instalar_dependencias(raiz: Path, python: Path) -> subprocess.Popen:
    """Arranca la instalación de dependencias y devuelve el proceso vivo.

    Se devuelve sin esperar para que el asistente pueda ir enseñando la salida
    según llega: es el paso más largo del instalador, y una pantalla quieta
    durante dos minutos parece colgada.
    """
    return subprocess.Popen(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(raiz / "requirements.txt"),
        ],
        cwd=str(raiz),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


# Se ejecuta con el Python del entorno, no con el del instalador: `app.db` y
# `app.auth` necesitan las dependencias recién instaladas. Y la contraseña
# entra por stdin y no por argumentos, que la línea de comandos de un proceso
# la ve cualquiera en la misma máquina.
#
# Aquí se guarda también el motor y el modelo, porque es la primera vez en toda
# la instalación en que se puede hablar con la base de datos, que es donde
# viven: son ajustes por usuario, no del `.env`.
GUION_CREAR_USUARIO = """
import sys
from dataclasses import replace

from app import ai_providers, auth, db

nombre, motor, modelo = sys.argv[1], sys.argv[2], sys.argv[3]
password = sys.stdin.read().strip()
db.init_db()
user = db.get_or_create_user(nombre)
db.set_password_hash(user["id"], auth.hash_password(password))

# `replace` sobre lo que ya hubiera: así reconfigurar el motor no le borra al
# usuario el resto de sus elecciones (voz, agente, herramientas).
actuales = ai_providers.get_settings(user["id"])
cambios = {"chat_provider": motor}
if modelo:
    cambios["chat_model"] = modelo
ai_providers.save_settings(user["id"], replace(actuales, **cambios))
print(user["id"])
"""


def crear_usuario(
    raiz: Path,
    python: Path,
    nombre: str,
    password: str,
    motor: str = "antigravity",
    modelo: str = "",
) -> str:
    """Crea o actualiza la cuenta y deja elegido su motor. Devuelve el id.

    No falla si ya existe: reinstalar con el mismo nombre debe dejarte entrar
    con la contraseña nueva, no plantarte un error.
    """
    resultado = subprocess.run(
        [str(python), "-c", GUION_CREAR_USUARIO, nombre, motor, modelo],
        cwd=str(raiz),
        input=password,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(raiz)},
    )
    if resultado.returncode != 0:
        # Con `check=True` la excepción solo enseña el comando entero —treinta
        # líneas de guion— y ni una palabra de lo que falló. Lo que hace falta
        # es el error de dentro, que es lo único que dice qué arreglar.
        detalle = (resultado.stderr or resultado.stdout).strip()
        ultima = detalle.splitlines()[-1] if detalle else "sin detalle"
        raise RuntimeError(f"No se pudo crear la cuenta: {ultima}")
    return resultado.stdout.strip().splitlines()[-1]

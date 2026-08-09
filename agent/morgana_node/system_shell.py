"""Ejecutar cosas en esta máquina, incluidas las que tardan.

Dos formas, y la diferencia importa:

- `ejecutar` es para lo que termina mientras esperas. Devuelve la salida entera.
- `lanzar` es para lo que no: una compilación, una instalación, una descarga.
  Devuelve un identificador al instante y el trabajo sigue corriendo mientras la
  conversación continúa; `salida` cuenta por dónde va.

Ese par es la razón de que este módulo exista. La ejecución remota que ya había
(`shell.run`) pasa por el servidor y compite contra el tiempo que una
conversación aguanta esperando —`NODE_RESULT_TIMEOUT_SECONDS`, 45 s—, así que
todo lo que dure más de un minuto era, en la práctica, imposible de pedir.

**Aquí no se consulta `fs_scope`.** Un intérprete de comandos completo llega a
todo el disco por definición, y filtrarlo por la ruta que aparezca en el texto
del comando no serviría de nada: `type`, `Get-Content` y `python -c` son tres
formas de leer lo mismo. Poner una comprobación que se esquiva sin esfuerzo es
peor que no ponerla, porque después alguien confía en ella.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

SHELL_TIMEOUT_DEFAULT = 120
SHELL_TIMEOUT_MAX = 900

# El servidor MCP manda la salida entera al modelo, así que hay un tope. La cola
# suele importar más que la cabeza: el error final está al final.
MAX_SALIDA_CHARS = 60_000

# Cuánto se guarda de un trabajo terminado antes de olvidarlo. Da margen para
# preguntar por él más tarde en la conversación sin que la memoria crezca sola.
RETENCION_TRABAJOS = 6 * 3600
MAX_TRABAJOS = 40


class ErrorShell(Exception):
    pass


def interprete() -> list[str]:
    """Con qué se ejecuta un comando en esta máquina.

    En Windows, PowerShell. No es una preferencia: `subprocess(shell=True)` usa
    `cmd.exe`, y ahí no funcionan ni los cmdlets ni las tuberías de objetos que
    aparecen en cualquier instrucción escrita para Windows en los últimos quince
    años. Se prefiere `pwsh` —PowerShell 7, con `&&` y `||`— y se cae a
    `powershell.exe`, que está siempre.

    `-NoProfile` porque el perfil del usuario puede tardar segundos e imprimir
    cosas que se colarían en la salida. `-NonInteractive` para que un cmdlet que
    quiera confirmación falle en vez de esperar a nadie.
    """
    if platform.system() == "Windows":
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh is None:  # pragma: no cover - Windows siempre trae uno
            raise ErrorShell("No encuentro PowerShell en esta máquina")
        return [pwsh, "-NoProfile", "-NonInteractive", "-Command"]

    shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
    return [shell, "-c"]


def directorio_trabajo(pedido: object, base: Path | None = None) -> Path:
    if not pedido:
        return base or Path.home()
    directorio = Path(str(pedido)).expanduser()
    if not directorio.is_absolute():
        directorio = (base or Path.home()) / directorio
    if not directorio.is_dir():
        raise ErrorShell(f"El directorio no existe: {directorio}")
    return directorio


def _truncar(texto: str) -> tuple[str, bool]:
    if len(texto) <= MAX_SALIDA_CHARS:
        return texto, False
    return texto[-MAX_SALIDA_CHARS:], True


def ejecutar(
    comando: str,
    directorio: object = None,
    timeout: int = SHELL_TIMEOUT_DEFAULT,
    base: Path | None = None,
) -> dict:
    """Un comando, esperando a que termine."""
    orden = str(comando or "").strip()
    if not orden:
        raise ErrorShell("No has dicho qué comando ejecutar")

    try:
        espera = int(timeout or SHELL_TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        raise ErrorShell("El timeout tiene que ser un número de segundos") from None
    espera = max(1, min(espera, SHELL_TIMEOUT_MAX))

    donde = directorio_trabajo(directorio, base)
    # stdin cerrado a propósito: un comando que pregunte algo debe fallar al
    # instante y no consumir el timeout entero esperando a alguien que no está.
    try:
        completado = subprocess.run(  # noqa: S603 - el comando es el encargo
            [*interprete(), orden],
            cwd=str(donde),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=espera,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as expirado:
        parcial = expirado.stdout if isinstance(expirado.stdout, str) else ""
        aviso = (
            f"Seguía corriendo tras {espera}s y se ha cortado. Si esto tarda "
            f"de verdad, lánzalo con `lanzar` en vez de con `ejecutar`."
        )
        if parcial.strip():
            aviso += f" Salida parcial: {parcial[-2000:]}"
        raise ErrorShell(aviso) from expirado
    except OSError as error:
        raise ErrorShell(f"No se pudo ejecutar: {error}") from error

    stdout, corte_out = _truncar(completado.stdout or "")
    stderr, corte_err = _truncar(completado.stderr or "")
    return {
        "codigo": completado.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncado": corte_out or corte_err,
        "directorio": str(donde),
    }


# ---------- Trabajos largos ----------

@dataclass
class _Trabajo:
    id: str
    comando: str
    directorio: str
    proceso: subprocess.Popen
    registro: Path
    empezado_en: float = field(default_factory=time.time)
    terminado_en: float = 0.0


_trabajos: dict[str, _Trabajo] = {}
_candado = threading.Lock()


def _limpiar() -> None:
    """Olvida los trabajos viejos ya terminados."""
    ahora = time.time()
    for identificador, trabajo in list(_trabajos.items()):
        if trabajo.proceso.poll() is None:
            continue
        if trabajo.terminado_en and ahora - trabajo.terminado_en > RETENCION_TRABAJOS:
            trabajo.registro.unlink(missing_ok=True)
            _trabajos.pop(identificador, None)


def lanzar(
    comando: str, directorio: object = None, base: Path | None = None
) -> dict:
    """Arranca algo y vuelve enseguida con su identificador.

    La salida va a un archivo y no a una tubería: nadie va a estar vaciándola
    mientras el trabajo corre, y una tubería sin vaciar bloquea al proceso en
    cuanto llena el buffer del sistema. Con un archivo, un `npm install` de diez
    minutos escribe todo lo que quiera y se lee cuando convenga.
    """
    orden = str(comando or "").strip()
    if not orden:
        raise ErrorShell("No has dicho qué comando lanzar")

    donde = directorio_trabajo(directorio, base)
    identificador = uuid.uuid4().hex[:8]
    registro = Path(tempfile.gettempdir()) / f"morgana-trabajo-{identificador}.log"

    try:
        salida = registro.open("w", encoding="utf-8", errors="replace")
    except OSError as error:
        raise ErrorShell(f"No pude abrir el registro del trabajo: {error}") from error

    opciones: dict = {
        "cwd": str(donde),
        "stdin": subprocess.DEVNULL,
        "stdout": salida,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        # Sin consola por delante y en su propio grupo, para poder pararlo
        # después sin llevarse por delante al agente.
        opciones["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        opciones["start_new_session"] = True

    try:
        proceso = subprocess.Popen(  # noqa: S603 - el comando es el encargo
            [*interprete(), orden], **opciones
        )
    except OSError as error:
        salida.close()
        registro.unlink(missing_ok=True)
        raise ErrorShell(f"No se pudo lanzar: {error}") from error
    finally:
        # El descriptor ya lo tiene el hijo; este proceso no necesita el suyo.
        salida.close()

    with _candado:
        _limpiar()
        if len(_trabajos) >= MAX_TRABAJOS:
            raise ErrorShell(
                f"Hay {len(_trabajos)} trabajos en marcha, que ya son "
                f"demasiados. Para alguno antes de lanzar otro."
            )
        _trabajos[identificador] = _Trabajo(
            id=identificador,
            comando=orden,
            directorio=str(donde),
            proceso=proceso,
            registro=registro,
        )

    return {
        "trabajo": identificador,
        "comando": orden,
        "directorio": str(donde),
        "pid": proceso.pid,
    }


def _leer_registro(trabajo: _Trabajo, desde: int) -> tuple[str, int, bool]:
    try:
        with trabajo.registro.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(max(0, int(desde or 0)))
            texto = handle.read()
            posicion = handle.tell()
    except OSError:
        return "", int(desde or 0), False
    recortado, cortado = _truncar(texto)
    return recortado, posicion, cortado


def salida(trabajo_id: str, desde: int = 0) -> dict:
    """Por dónde va un trabajo, y lo que ha escrito desde la última vez.

    `desde` es la posición que devolvió la consulta anterior. Preguntando con
    ella se lee solo lo nuevo, que es lo que permite seguir algo largo sin
    releer la salida entera cada vez.
    """
    with _candado:
        trabajo = _trabajos.get(str(trabajo_id or ""))
    if trabajo is None:
        raise ErrorShell(f"No hay ningún trabajo «{trabajo_id}»")

    codigo = trabajo.proceso.poll()
    if codigo is not None and not trabajo.terminado_en:
        trabajo.terminado_en = time.time()

    texto, posicion, cortado = _leer_registro(trabajo, desde)
    return {
        "trabajo": trabajo.id,
        "comando": trabajo.comando,
        "terminado": codigo is not None,
        "codigo": codigo,
        "salida": texto,
        "posicion": posicion,
        "truncado": cortado,
        "segundos": round(
            (trabajo.terminado_en or time.time()) - trabajo.empezado_en, 1
        ),
    }


def parar(trabajo_id: str) -> dict:
    with _candado:
        trabajo = _trabajos.get(str(trabajo_id or ""))
    if trabajo is None:
        raise ErrorShell(f"No hay ningún trabajo «{trabajo_id}»")

    if trabajo.proceso.poll() is not None:
        return {"trabajo": trabajo.id, "parado": False, "terminado": True}

    try:
        trabajo.proceso.terminate()
        trabajo.proceso.wait(timeout=10)
    except subprocess.TimeoutExpired:
        trabajo.proceso.kill()
    except OSError:
        pass
    trabajo.terminado_en = time.time()
    return {"trabajo": trabajo.id, "parado": True, "terminado": True}


def trabajos() -> dict:
    with _candado:
        _limpiar()
        vivos = [
            {
                "trabajo": trabajo.id,
                "comando": trabajo.comando,
                "directorio": trabajo.directorio,
                "terminado": trabajo.proceso.poll() is not None,
                "codigo": trabajo.proceso.poll(),
                "segundos": round(
                    (trabajo.terminado_en or time.time()) - trabajo.empezado_en, 1
                ),
            }
            for trabajo in _trabajos.values()
        ]
    return {"trabajos": vivos}

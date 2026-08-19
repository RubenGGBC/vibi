"""Instalar la CLI de Antigravity, que es el motor de Vibi.

Se ejecutan los guiones oficiales de Google en vez de replicar lo que hacen.
Por dentro consultan un manifiesto por plataforma y bajan un binario Go con su
sha512; copiar esa lógica aquí obligaría a perseguir sus cambios, y el día que
la muevan Vibi dejaría de instalarse sin que nadie se entere.

**No está en npm.** Comprobado en el registro el 19/08/2026:
`@google/antigravity-cli` no existe y el `antigravity-cli` que sí está es de un
tercero, de noviembre de 2025, con un binario llamado `kirox`. Lo que sí vive en
npm es `@google/gemini-cli`, pero esa es otra CLI —da el comando `gemini`— y el
motor de Vibi pilota `agy`.

Lo que NO se puede automatizar es el login: abre OAuth y exige un terminal de
verdad (`bubbletea: could not open TTY`). Eso lo hace el usuario, y el
instalador solo puede decírselo claro y comprobarlo después.

**Solo biblioteca estándar.**
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

GUION_UNIX = "https://antigravity.google/cli/install.sh"
GUION_WINDOWS = "https://antigravity.google/cli/install.ps1"


class NoSePuedeInstalar(RuntimeError):
    """Aquí no hay guion oficial que ejecutar."""


def comando_de_instalacion(so: str) -> list[str]:
    """El comando que trae `agy` a esta máquina.

    `-NoProfile` en Windows para que un perfil de PowerShell con manías no le
    cambie el entorno al guion oficial a mitad de instalación.
    """
    if so == "windows":
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"irm {GUION_WINDOWS} | iex",
        ]
    if so in ("macos", "linux"):
        return ["bash", "-c", f"curl -fsSL {GUION_UNIX} | bash"]
    raise NoSePuedeInstalar(
        "Antigravity solo publica instalador para Windows, macOS y Linux."
    )


def _candidatos() -> tuple[Path, ...]:
    """Dónde deja el binario cada guion oficial.

    Hace falta mirar aquí y no solo en el PATH: el PATH de este proceso se fijó
    al arrancar y no se entera de que acaba de aparecer un ejecutable nuevo, así
    que justo después de instalarlo bien diríamos que sigue sin estar.
    """
    casa = Path.home()
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or (casa / "AppData" / "Local"))
        return (
            base / "agy" / "bin" / "agy.exe",
            casa / "AppData" / "Local" / "agy" / "bin" / "agy.exe",
        )
    return (casa / ".local" / "bin" / "agy",)


def donde_esta() -> str:
    """La ruta de `agy`, o vacío si no está por ninguna parte."""
    en_path = shutil.which("agy")
    if en_path:
        return en_path
    for candidato in _candidatos():
        if candidato.is_file():
            return str(candidato)
    return ""


def destino() -> Path:
    """Dónde va a quedar tras instalarlo."""
    return _candidatos()[0]


def instalar(so: str) -> subprocess.Popen:
    """Lanza la instalación y devuelve el proceso, sin esperarlo.

    Sin esperar para que quien llame pueda ir enseñando la salida según llega:
    baja unos cuantos megas y una pantalla quieta parece colgada.
    """
    return subprocess.Popen(
        comando_de_instalacion(so),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def tiene_sesion(ruta: str = "") -> bool:
    """Si `agy` está instalado Y con la cuenta ya iniciada.

    Estar instalado no basta: sin login, el primer turno de Vibi falla con un
    error de autenticación que no dice nada del instalador. Se pregunta por sus
    modelos, que es lo más barato que solo contesta con sesión abierta.
    """
    binario = ruta or donde_esta()
    if not binario:
        return False
    try:
        resultado = subprocess.run(
            [binario, "models"],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    salida = f"{resultado.stdout}{resultado.stderr}".lower()
    if resultado.returncode != 0:
        return False
    # Sin sesión lo dice con todas las letras en vez de fallar.
    return "not signed in" not in salida and "sign in" not in salida

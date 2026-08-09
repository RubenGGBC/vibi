"""El proceso `agy` vivo, que es lo único para lo que sigue haciendo falta un PTY.

`agy` comprueba que hay un terminal de verdad antes de arrancar, así que se
lanza dentro de un pseudoterminal. Pero ya no se lee de ahí: la respuesta se
sigue por el language server que el propio proceso levanta (ver `agy_client`).
El PTY queda para dos cosas nada más: mantenerlo en pie y teclearle el turno.

Teclear en vez de usar `SendUserCascadeMessage` no es pereza: esa llamada
cuesta dos segundos fijos, medidos, y el PTY hace falta igualmente.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import agy_client

log = logging.getLogger("morgana.agy")

# Teclear de golpe hace que la interfaz se coma caracteres; carácter a carácter
# un mensaje largo tarda un segundo entero. En bloques pequeños no se pierde
# nada y el turno empieza antes.
TYPE_CHUNK = 24
TYPE_DELAY = 0.012

# Lo que se le da al language server para decir que sigue ahí. Es un viaje a
# localhost: si tarda más que esto, no es que vaya lento, es que está colgado.
HEALTH_TIMEOUT = 2.0

_PORT = re.compile(r"listening on random port at (\d+) for HTTP$", re.MULTILINE)


class AgyUnavailable(RuntimeError):
    """No se pudo tener a `agy` en pie; el turno tiene que ir por otro motor."""


def port_from_log(text: str) -> int | None:
    """El puerto HTTP del language server, si ya lo ha anunciado.

    Hay dos puertos y solo vale uno: el de gRPC va por HTTPS con certificado
    propio, mientras que el de HTTP acepta el JSON plano que usamos.
    """
    found = _PORT.search(text)
    return int(found.group(1)) if found else None


def wait_for_port(log_path, timeout: float = 90.0, poll: float = 0.1) -> int | None:
    """Espera a que el language server anuncie su puerto en el log.

    Es la señal de que `agy` está listo de verdad. Antes se daba por listo tras
    unos segundos de silencio en pantalla, y como la CLI podía callarse
    mientras seguía inicializando, el primer turno tecleado se perdía.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            texto = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            texto = ""  # aún no existe
        port = port_from_log(texto)
        if port is not None:
            return port
        time.sleep(poll)
    return None


def wait_until_idle(
    log_path, quiet: float = 2.5, timeout: float = 60.0, poll: float = 0.1
) -> bool:
    """Espera a que `agy` termine de arrancar, no solo a que abra el puerto.

    El puerto aparece antes de que la interfaz acepte entrada: la CLI sigue
    resolviendo el modelo un par de segundos más, y lo que se teclee mientras
    se pierde. Cuando acaba, deja de escribir en el log, y ese silencio sí es
    fiable —el de la pantalla no lo era, porque la interfaz redibuja sola—.
    """
    deadline = time.time() + timeout
    ultimo_tamano = -1
    ultimo_cambio = time.time()
    while time.time() < deadline:
        try:
            tamano = log_path.stat().st_size
        except OSError:
            tamano = -1
        if tamano != ultimo_tamano:
            ultimo_tamano = tamano
            ultimo_cambio = time.time()
        elif time.time() - ultimo_cambio >= quiet:
            return True
        time.sleep(poll)
    return False


def type_text(pty, text: str) -> None:
    """Teclea el turno y pulsa intro, como haría una persona."""
    # Un salto de línea lo interpretaría como enviar el mensaje a medias.
    limpio = " ".join(text.split("\n"))
    for inicio in range(0, len(limpio), TYPE_CHUNK):
        pty.write(limpio[inicio : inicio + TYPE_CHUNK])
        time.sleep(TYPE_DELAY)
    pty.write("\r")


def _open_pty(command: list[str], workspace: str):
    """Abre `agy` en un pseudoterminal, con lo que haya en cada sistema.

    En Windows hace falta `pywinpty` para hablar con ConPTY; en Linux y Mac
    basta el módulo `pty` de la biblioteca estándar.
    """
    if sys.platform == "win32":
        try:
            from winpty import PtyProcess  # noqa: PLC0415
        except ImportError as error:
            raise AgyUnavailable(
                "falta pywinpty, que en Windows hace falta para abrir agy"
            ) from error
        try:
            return PtyProcess.spawn(command, dimensions=(50, 200), cwd=workspace)
        except Exception as error:
            raise AgyUnavailable(f"no se pudo lanzar {command[0]}: {error}") from error

    try:
        import ptyprocess  # noqa: PLC0415
    except ImportError as error:
        raise AgyUnavailable(
            "falta ptyprocess, que hace falta para abrir agy en este sistema"
        ) from error
    try:
        return ptyprocess.PtyProcessUnicode.spawn(
            command, dimensions=(50, 200), cwd=workspace
        )
    except Exception as error:
        raise AgyUnavailable(f"no se pudo lanzar {command[0]}: {error}") from error


class AgyProcess:
    """Una instancia de `agy` viva, con su language server escuchando."""

    def __init__(self, pty, port: int, log_path: Path) -> None:
        self.pty = pty
        self.port = port
        self.log_path = log_path

    @classmethod
    def start(
        cls,
        binary: str,
        workspace: str,
        model: str = "",
        timeout: float = 90.0,
        effort: str = "",
    ) -> "AgyProcess":
        os.makedirs(workspace, exist_ok=True)
        log_path = Path(tempfile.gettempdir()) / f"morgana-agy-{uuid.uuid4().hex}.log"

        command = [binary or "agy"]
        if model:
            command += ["--model", model]
        if effort:
            command += ["--effort", effort]
        # Nadie lee el pseudoterminal: `_drain` tira la salida. Si `agy` pidiera
        # permiso para usar una herramienta, la pregunta se quedaría esperando
        # una respuesta que no va a llegar nunca y el turno moriría de timeout.
        # Auto-aprobar es admisible porque quien pone el límite es el sandbox de
        # alrededor —el contenedor, que solo ve el workspace—, no esta pregunta.
        # Fuera de un contenedor esto le daría el disco entero.
        command += ["--dangerously-skip-permissions"]
        command += ["--log-file", str(log_path)]

        pty = _open_pty(command, str(workspace))
        # Si nadie lee la salida, el buffer se llena y `agy` se queda parado.
        threading.Thread(target=_drain, args=(pty,), daemon=True).start()

        port = wait_for_port(log_path, timeout=timeout)
        if port is None:
            _kill(pty)
            raise AgyUnavailable("agy no llegó a levantar su language server")
        # El puerto no basta: la interfaz tarda un poco más en aceptar entrada.
        wait_until_idle(log_path, timeout=timeout)
        log.info("agy listo, language server en el puerto %s", port)
        return cls(pty, port, log_path)

    def type(self, text: str) -> None:
        type_text(self.pty, text)

    def alive(self) -> bool:
        try:
            return bool(self.pty.isalive())
        except Exception:
            return False

    def healthy(self, timeout: float = HEALTH_TIMEOUT) -> bool:
        """Vivo de verdad, no solo respirando.

        `alive()` solo dice que el pseudoterminal sigue abierto, y así es
        justamente como se cuelga `agy`: el proceso figura vivo mientras la
        interfaz ha dejado de aceptar lo que se le teclea. Preguntárselo al
        language server es lo único que distingue las dos cosas.

        Importa porque de esto dependía que Morgana se recuperase. Un proceso
        enfermo que pasa por vivo se reutiliza en cada turno, y cada turno
        vuelve a fallar: el usuario se quedaba contestado por Claude hasta
        reiniciar el servidor.
        """
        if not self.alive():
            return False
        try:
            agy_client.AgyClient(self.port, timeout=timeout).conversations()
        except agy_client.AgyError as error:
            log.warning("agy no responde en el puerto %s: %s", self.port, error)
            return False
        return True

    def kill(self) -> None:
        _kill(self.pty)
        try:
            self.log_path.unlink(missing_ok=True)
        except OSError:
            pass


def _drain(pty) -> None:
    """Vacía la salida del pseudoterminal, que ya no se lee para nada más."""
    while True:
        try:
            if not pty.read(4096):
                time.sleep(0.01)
        except Exception:
            return


def _kill(pty) -> None:
    try:
        pty.terminate(True)
    except Exception:
        log.debug("el proceso agy ya no estaba")

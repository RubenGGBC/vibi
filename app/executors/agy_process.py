"""El proceso `agy` vivo, que es lo único para lo que sigue haciendo falta un PTY.

`agy` comprueba que hay un terminal de verdad antes de arrancar, así que se
lanza dentro de un pseudoterminal. Pero ya no se lee de ahí: la respuesta se
sigue por el language server que el propio proceso levanta (ver `agy_client`).
El PTY queda para dos cosas nada más: mantenerlo en pie y teclearle el turno.

Teclear en vez de usar `SendUserCascadeMessage` no es pereza: esa llamada
cuesta dos segundos fijos, medidos, y el PTY hace falta igualmente.
"""
from __future__ import annotations

import codecs
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
from ..config import settings

log = logging.getLogger("vibi.agy")

# Errores de lectura seguidos que se toleran antes de dar por perdido el
# vaciado de la salida. Reintentar es lo importante —un error suelto no puede
# dejar a `agy` sin quien le vacíe—, pero uno que no cesa no se arregla
# insistiendo, y girar sin tope gastaría una CPU entera.
DRAIN_MAX_ERRORES = 5
DRAIN_PAUSA_ERROR = 0.05

# Los logs de `agy` que se guardan al caerse. Es lo único que cuenta si el
# turno tecleado llegó siquiera a la CLI, y borrarlo justo al fallar dejaba el
# fallo mudo; pero sin tope llenarían el disco del contenedor.
PREFIJO_LOG_CAIDO = "vibi-agy-caido-"
LOGS_CAIDOS_QUE_SE_GUARDAN = 5

# Lo que se le da al language server para decir que sigue ahí. Es un viaje a
# localhost: si tarda más que esto, no es que vaya lento, es que está colgado.
HEALTH_TIMEOUT = 2.0
# Evita dos viajes iguales al language server cuando el precalentado y el
# turno llegan juntos. Solo se cachean éxitos y `alive()` se comprueba siempre.
HEALTH_CACHE_SECONDS = 1.0

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


def type_text(pty, text: str, chunk: int = 0, delay: float = -1.0) -> None:
    """Teclea el turno y pulsa intro, como haría una persona.

    El ritmo sale de la configuración para poder calibrarlo contra la CLI real
    —lo que se pierde al ir rápido no se ve en un test, se ve en el texto que
    `agy` registra—, y los argumentos están para medirlo sin tocar los ajustes.
    """
    if chunk <= 0:
        chunk = max(1, settings.agy_type_chunk)
    if delay < 0:
        delay = max(0.0, settings.agy_type_delay_ms) / 1000.0
    # Un salto de línea lo interpretaría como enviar el mensaje a medias.
    limpio = " ".join(text.split("\n"))
    for inicio in range(0, len(limpio), chunk):
        pty.write(limpio[inicio : inicio + chunk])
        time.sleep(delay)
    pty.write("\r")


def _tolerar_bytes_invalidos(pty):
    """Que un byte a medias no tumbe al que vacía la salida.

    `ptyprocess` construye su decodificador con `errors='strict'` y `spawn` no
    deja elegir otro. Por aquí no pasa texto ordenado, pasa una interfaz de
    terminal repintándose, así que basta un byte que no forme UTF-8 válido para
    que el decodificador empiece a lanzar y el hilo del vaciado se caiga.

    En Windows no hay nada que tocar: `pywinpty` entrega texto ya decodificado.
    """
    if hasattr(pty, "decoder"):
        pty.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    return pty


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
        return _tolerar_bytes_invalidos(
            ptyprocess.PtyProcessUnicode.spawn(
                command, dimensions=(50, 200), cwd=workspace
            )
        )
    except Exception as error:
        raise AgyUnavailable(f"no se pudo lanzar {command[0]}: {error}") from error


class AgyProcess:
    """Una instancia de `agy` viva, con su language server escuchando."""

    def __init__(
        self,
        pty,
        port: int,
        log_path: Path,
        drenando: threading.Event | None = None,
    ) -> None:
        self.pty = pty
        self.port = port
        self.log_path = log_path
        self._healthy_at: float | None = None
        # La marca que el hilo del vaciado apaga al terminar. Sin él, `agy`
        # deja de aceptar entrada en cuanto llena el buffer del
        # pseudoterminal, así que quien no traiga la suya se da por drenado.
        if drenando is None:
            drenando = threading.Event()
            drenando.set()
        self._drenando = drenando

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
        log_path = Path(tempfile.gettempdir()) / f"vibi-agy-{uuid.uuid4().hex}.log"

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
        drenando = threading.Event()
        drenando.set()
        threading.Thread(target=_drain, args=(pty, drenando), daemon=True).start()

        port = wait_for_port(log_path, timeout=timeout)
        if port is None:
            _kill(pty)
            raise AgyUnavailable("agy no llegó a levantar su language server")
        # El puerto no basta: la interfaz tarda un poco más en aceptar entrada.
        wait_until_idle(log_path, timeout=timeout)
        log.info("agy listo, language server en el puerto %s", port)
        return cls(pty, port, log_path, drenando)

    def type(self, text: str) -> None:
        type_text(self.pty, text)

    def alive(self) -> bool:
        try:
            return bool(self.pty.isalive())
        except Exception:
            return False

    def draining(self) -> bool:
        """¿Sigue habiendo alguien vaciando la salida del pseudoterminal?"""
        return self._drenando.is_set()

    def healthy(
        self,
        timeout: float = HEALTH_TIMEOUT,
        max_age: float = HEALTH_CACHE_SECONDS,
    ) -> bool:
        """Vivo de verdad, no solo respirando.

        `alive()` solo dice que el pseudoterminal sigue abierto, y así es
        justamente como se cuelga `agy`: el proceso figura vivo mientras la
        interfaz ha dejado de aceptar lo que se le teclea.

        Hay dos maneras de llegar a eso y hacen falta las dos comprobaciones.
        Una es que la CLI se atasque, y esa solo la ve el language server. La
        otra es que se quede sin quien le vacíe la salida, y esa el language
        server no la ve: contesta igual de bien mientras la interfaz está
        bloqueada escribiendo, así que el proceso pasaba por sano y el turno se
        tecleaba al vacío.

        Importa porque de esto dependía que Vibi se recuperase. Un proceso
        enfermo que pasa por vivo se reutiliza en cada turno, y cada turno
        vuelve a fallar: el usuario se quedaba contestado por Claude hasta
        reiniciar el servidor.
        """
        if not self.alive():
            self._healthy_at = None
            return False
        if not self.draining():
            self._healthy_at = None
            log.warning(
                "nadie vacía la salida de agy en el puerto %s: "
                "dejará de aceptar lo que se le teclee",
                self.port,
            )
            return False
        now = time.monotonic()
        if (
            self._healthy_at is not None
            and max_age > 0
            and now - self._healthy_at <= max_age
        ):
            return True
        try:
            agy_client.AgyClient(self.port, timeout=timeout).conversations()
        except agy_client.AgyError as error:
            self._healthy_at = None
            log.warning("agy no responde en el puerto %s: %s", self.port, error)
            return False
        self._healthy_at = time.monotonic()
        return True

    def kill(self, conservar_log: bool = False) -> None:
        """Mata el proceso, guardando su log si se ha caído.

        El log de `agy` es lo único que cuenta qué estaba haciendo la CLI
        cuando dejó de aceptar entrada, y en particular si el turno tecleado
        llegó a entrar. Borrarlo justo al fallar dejaba el fallo mudo, así que
        el diagnóstico se destruía siempre en el único momento en que hacía
        falta. En los cierres ordenados sí se borra: ahí no hay nada que mirar.
        """
        self._healthy_at = None
        _kill(self.pty)
        if conservar_log:
            _guardar_log_caido(self.log_path)
            return
        try:
            self.log_path.unlink(missing_ok=True)
        except OSError:
            pass


def _drain(pty, drenando: threading.Event | None = None) -> None:
    """Vacía la salida del pseudoterminal, que ya no se lee para nada más.

    Tirar la salida no es opcional aunque no le interese a nadie. Cuando nadie
    la vacía, `agy` se bloquea escribiendo en cuanto llena el buffer del
    pseudoterminal —y le basta con repintar la pantalla una vez—, y una CLI
    bloqueada escribiendo deja de leer lo que se le teclea. El proceso sigue
    vivo y su language server sigue contestando, así que el turno se teclea al
    vacío y lo único que se ve es que `agy` «no registró el turno tecleado».

    Por eso un error de lectura no lo termina: se reintenta. Antes cualquier
    excepción mataba el hilo y ninguna dejaba rastro, así que Vibi seguía
    teclando contra un `agy` que ya no podía escucharla. Y cuando el vaciado
    termina de verdad se avisa, para que el proceso deje de pasar por sano.
    """
    errores = 0
    try:
        while True:
            try:
                if not pty.read(4096):
                    # `pywinpty` puede volver sin datos en vez de esperarlos, y
                    # sin la pausa el hilo se comería una CPU entera.
                    time.sleep(0.01)
            except EOFError:
                return  # el proceso se ha ido: fin legítimo
            except Exception as error:  # noqa: BLE001 - hay que seguir vaciando
                errores += 1
                if errores >= DRAIN_MAX_ERRORES:
                    log.warning(
                        "no se puede vaciar la salida de agy (%s); lo doy por perdido",
                        error,
                    )
                    return
                time.sleep(DRAIN_PAUSA_ERROR)
            else:
                errores = 0
    finally:
        if drenando is not None:
            drenando.clear()


def _guardar_log_caido(log_path: Path) -> None:
    """Aparta el log del `agy` que acaba de fallar, y tira los más viejos."""
    try:
        if not log_path.exists():
            return
        marca = time.strftime("%Y%m%d-%H%M%S")
        destino = log_path.with_name(f"{PREFIJO_LOG_CAIDO}{marca}-{log_path.name}")
        log_path.rename(destino)
        log.warning("guardado el log del agy caído en %s", destino)
        _purgar_logs_caidos(destino.parent)
    except OSError as error:
        log.debug("no se pudo guardar el log del agy caído: %s", error)


def _purgar_logs_caidos(directorio: Path) -> None:
    def antiguedad(ruta: Path) -> float:
        try:
            return ruta.stat().st_mtime
        except OSError:
            return 0.0

    try:
        guardados = sorted(
            directorio.glob(f"{PREFIJO_LOG_CAIDO}*.log"), key=antiguedad
        )
    except OSError:
        return
    for viejo in guardados[:-LOGS_CAIDOS_QUE_SE_GUARDAN]:
        try:
            viejo.unlink()
        except OSError:
            pass


def _kill(pty) -> None:
    try:
        pty.terminate(True)
    except Exception:
        log.debug("el proceso agy ya no estaba")

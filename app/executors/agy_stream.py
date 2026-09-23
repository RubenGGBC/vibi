"""`agy` por su interfaz documentada: stream-json por la entrada y la salida.

Hasta el 23/09/2026 Vibi manejaba `agy` como una persona: lo abría en un
pseudoterminal, le tecleaba el turno y leía la respuesta por el language
server que la CLI levanta en localhost (ver `agy_process` y `agy_client`). Esa
API era interna, y la versión 1.2.9 —que `agy` se instaló solo esa mañana— la
cerró con un token CSRF que no se publica en ninguna parte. Cada llamada volvía
con `401 missing CSRF token`, ninguna conversación llegaba a abrirse y todos
los turnos caían a Claude después de 30 s de espera.

Esto usa lo que Google sí documenta para que otro programa lleve la sesión:

    agy --input-format stream-json --output-format stream-json --print=

Por la entrada va una línea JSON por turno (`{"event":"user","message":
{"content": …}}`), y por la salida llegan eventos tipados —`init`,
`step_update` con un `step_type` de vocabulario cerrado, y `result` al cerrar
cada turno—. Un proceso es una conversación y la mantiene entre turnos.

**Ofrece la misma forma que el proceso y el cliente de antes** (`start`,
`type`, `alive`, `healthy`, `kill`; `conversations`, `user_input_count`,
`stream_updates`, `stop`) para que el motor no cambie: todo lo que sabe hacer
bien —reintentar un turno mudo, cortar por silencio, marcar procedencia, poner
cara según la herramienta— sigue valiendo tal cual, porque lo que recibe siguen
siendo `agy_client.Update`.

Las dos diferencias que el motor sí nota:

  - **`/new` no existe en este modo**: cada proceso es ya una conversación.
    Teclear `/new` pasa a otro proceso —el de repuesto, que ya estaba
    arrancado esperando; si no lo hay, uno nuevo, ~3 s medidos—, y la
    conversación nueva aparece en `conversations()` como aparecía antes.
  - **No hay forma de cortar un turno a medias**, así que `stop` cierra ese
    proceso y pone a atender al de repuesto. El motor ya trata un turno
    cortado como sesión perdida.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator

from . import agy_client
from ..config import settings
from .agy_process import (
    SUFIJOS_DE_ESFUERZO,
    AgyUnavailable,
    _guardar_log_caido,
)

log = logging.getLogger("vibi.agy")

# Lo que se espera al evento `init`. Medido: 2,9 s en este equipo.
ARRANQUE_TIMEOUT = 60.0

# Cómo se traduce el estado de un paso al vocabulario de `agy_client`, que es
# el que entiende el motor para decidir si queda una herramienta a medias.
ESTADOS = {
    "ACTIVE": "CORTEX_STEP_STATUS_RUNNING",
    "RUNNING": "CORTEX_STEP_STATUS_RUNNING",
    "PENDING": "CORTEX_STEP_STATUS_PENDING",
    "WAITING": "CORTEX_STEP_STATUS_PENDING",
    "DONE": agy_client.STATUS_DONE,
    "ERROR": "CORTEX_STEP_STATUS_ERROR",
    "CANCELED": "CORTEX_STEP_STATUS_CANCELED",
    "CANCELLED": "CORTEX_STEP_STATUS_CANCELED",
}

_FIN = object()

# Los modelos que esta CLI ya ha dicho que no conoce. Cada rechazo cuesta un
# arranque entero (~3 s), y el mismo ajuste se vuelve a pedir en cada sesión.
_RECHAZADOS: set[str] = set()


def mensaje(texto: str) -> str:
    """Una línea de entrada: un turno del usuario."""
    return json.dumps(
        {"event": "user", "message": {"content": texto}}, ensure_ascii=False
    ) + "\n"


def tipo_de_herramienta(paso: dict) -> str:
    """El nombre con el que el motor clasifica la herramienta.

    `run_command` se traduce al tipo de siempre porque de él cuelga el reloj
    del turno: mientras un comando corre, no hay silencio que cortar. El resto
    va con su nombre, y el servidor MCP delante cuando viene, que es lo que
    miran la procedencia y las caras.
    """
    nombre = str(paso.get("tool_name") or "")
    if nombre == "run_command":
        return agy_client.STEP_RUN_COMMAND
    info = paso.get("tool_info") or {}
    parametros = info.get("parameters") if isinstance(info, dict) else None
    if nombre == "call_mcp_tool" and isinstance(parametros, dict):
        # Las de un servidor MCP llegan todas como `call_mcp_tool`, con el
        # servidor y la herramienta de verdad entre los parámetros.
        servidor = str(parametros.get("ServerName") or "")
        herramienta = str(parametros.get("ToolName") or "")
        if servidor and herramienta:
            return f"mcp__{servidor}__{herramienta}"
    return nombre


def detalle_de_herramienta(paso: dict) -> str:
    info = paso.get("tool_info") or {}
    parametros = info.get("parameters") if isinstance(info, dict) else None
    cuerpo = dict(parametros) if isinstance(parametros, dict) else {}
    # Los argumentos de una MCP van anidados y no se leen en una línea.
    cuerpo.pop("Arguments", None)
    cuerpo.setdefault("toolName", str(paso.get("tool_name") or ""))
    return agy_client._detalle_del_paso({"tool": cuerpo})


class Traductor:
    """De eventos de stream-json a las `Update` que ya entiende el motor.

    El texto se entrega acumulado —todo lo que el modelo ha dicho en el turno,
    con un salto entre bloques separados por herramientas— porque así lo
    espera `TurnText`, que va quedándose solo con lo nuevo.
    """

    def __init__(self) -> None:
        self.texto = ""
        self._paso_de_texto: int | None = None
        self._herramientas: dict[int, tuple[str, str]] = {}
        self._pasos: dict[int, agy_client.Paso] = {}

    def _update(self, **kwargs) -> agy_client.Update:
        herramientas = tuple(self._herramientas[i] for i in sorted(self._herramientas))
        return agy_client.Update(
            herramientas=herramientas,
            pasos=tuple(self._pasos[i] for i in sorted(self._pasos)),
            activity=True,
            tools_running=any(
                estado in agy_client.ESTADOS_EN_CURSO for _, estado in herramientas
            ),
            **kwargs,
        )

    def paso(self, paso: dict) -> agy_client.Update | None:
        tipo = paso.get("step_type")
        indice = int(paso.get("step_index") or 0)
        estado = ESTADOS.get(str(paso.get("state") or "").upper(), str(paso.get("state") or ""))
        if tipo == "agent_response":
            delta = paso.get("text_delta") or ""
            if delta:
                if (
                    self._paso_de_texto is not None
                    and indice != self._paso_de_texto
                    and self.texto
                    and not self.texto.endswith("\n")
                ):
                    # Un bloque nuevo tras una herramienta: sin separación, el
                    # «ahora lo miro» y la respuesta se leerían pegados.
                    self.texto += "\n\n"
                self._paso_de_texto = indice
                self.texto += delta
            return self._update(
                text=self.texto if self.texto else None,
                done=estado == agy_client.STATUS_DONE,
                trabajando=True,
            )
        if tipo == "tool":
            nombre = tipo_de_herramienta(paso)
            self._herramientas[indice] = (nombre, estado)
            self._pasos[indice] = agy_client.Paso(
                tipo=nombre, estado=estado, detalle=detalle_de_herramienta(paso)
            )
            return self._update(trabajando=True)
        # `user_input` y lo que venga: cuenta como señal de vida.
        return self._update(trabajando=True)

    def final(self) -> agy_client.Update:
        return self._update(
            text=self.texto if self.texto else None, done=True, trabajando=False
        )


class _Conexion:
    """Un `agy` lanzado: su proceso, sus eventos y su conversación.

    Cada una lleva su log propio porque dos pueden estar vivas a la vez —la que
    atiende y la de repuesto—, y con uno compartido se pisarían el motivo de la
    caída.
    """

    def __init__(self, popen, log_path: Path) -> None:
        self.popen = popen
        self.eventos: queue.Queue = queue.Queue()
        self.listo = threading.Event()
        self.conversation_id = ""
        self.entradas = 0
        self.log_path = log_path

    @property
    def stderr_path(self) -> Path:
        return self.log_path.with_suffix(".stderr")

    def viva(self) -> bool:
        return self.popen is not None and self.popen.poll() is None


def _nuevo_log() -> Path:
    return Path(tempfile.gettempdir()) / f"vibi-agy-{uuid.uuid4().hex}.log"


class AgyStreamProcess:
    """Un `agy` en modo stream-json: una conversación viva, y otra esperando.

    Aquí cada conversación nueva es un proceso nuevo, y arrancarlo son ~3 s
    medidos —más los servidores MCP— que se pagaban dentro del turno: en cada
    invocación de voz, en cada hilo nuevo y después de cortar un turno. Por eso
    se deja siempre otro `agy` arrancado de repuesto, ya con su `init`, y
    pedir conversación nueva es cambiar de uno a otro. El repuesto no gasta
    cuota: hasta que no se le escribe no habla con nadie.
    """

    def __init__(
        self,
        binary: str,
        workspace: str,
        model: str = "",
        effort: str = "",
        repuesto: bool = True,
    ) -> None:
        self._binary = binary or "agy"
        self._workspace = str(workspace)
        self._model = model
        self._effort = effort
        self._con_repuesto = repuesto
        self._lock = threading.Lock()
        # La que atiende. Empieza sin proceso para que un objeto recién hecho
        # —los tests lo usan así— ya tenga dónde apuntar su conversación.
        self._actual = _Conexion(None, _nuevo_log())
        self._repuesto: _Conexion | None = None
        self._preparando: threading.Thread | None = None
        self._lock_repuesto = threading.Lock()
        self._cerrado = False
        self.conocidas: list[str] = []
        # Si alguien ya ha pedido esta conversación con `/new`. Hasta entonces
        # no se enseña en `conversations()`, para que quien la pida la vea
        # aparecer como aparecía con el pseudoterminal.
        self._reservada = False
        # Lo apunta `_abrir_conversacion`; se conserva por compatibilidad.
        self.conversacion_activa: str | None = None
        # No hay puerto: nada escucha en localhost. Se deja por si alguien lo
        # registra en un log.
        self.port = None

    # Lo que el motor y el cliente leen es siempre de la conexión que atiende.

    @property
    def conversation_id(self) -> str:
        return self._actual.conversation_id

    @conversation_id.setter
    def conversation_id(self, valor: str) -> None:
        self._actual.conversation_id = valor

    @property
    def entradas(self) -> int:
        return self._actual.entradas

    @entradas.setter
    def entradas(self, valor: int) -> None:
        self._actual.entradas = valor

    @property
    def log_path(self) -> Path:
        return self._actual.log_path

    @property
    def _popen(self):
        return self._actual.popen

    @property
    def _eventos(self) -> queue.Queue:
        return self._actual.eventos

    @classmethod
    def start(
        cls,
        binary: str,
        workspace: str,
        model: str = "",
        timeout: float = ARRANQUE_TIMEOUT,
        effort: str = "",
        repuesto: bool = True,
    ) -> "AgyStreamProcess":
        if model in _RECHAZADOS:
            model, effort = settings.antigravity_model, ""
        proceso = cls(binary, workspace, model, effort, repuesto)
        # Con el pseudoterminal, un modelo o un esfuerzo que `agy` no conoce
        # eran un aviso y seguía con los suyos; en este modo son un error. Se
        # hace a mano lo mismo que hacía él: quitar lo que no acepta.
        for _ in range(3):
            try:
                proceso._estrenar(proceso._lanzar(timeout))
                break
            except AgyUnavailable as error:
                motivo = str(error)
                if proceso._effort and "--effort is not supported" in motivo:
                    log.info("agy no admite --effort con %s; sigo sin él", model)
                    proceso._effort = ""
                elif proceso._model and "not recognized as a known model" in motivo:
                    # Pasa con un modelo de otro motor guardado como el de
                    # agy —`claude-haiku-4-5`—. Se cae al del servidor antes
                    # que al de la CLI: el de la CLI es el que Vibi no elige.
                    respaldo = settings.antigravity_model
                    _RECHAZADOS.add(proceso._model)
                    log.warning(
                        "agy no conoce el modelo %s; sigo con %s",
                        proceso._model, respaldo or "el suyo por defecto",
                    )
                    proceso._model = "" if respaldo == proceso._model else respaldo
                    proceso._effort = ""
                else:
                    raise
        else:
            raise AgyUnavailable("agy no llegó a arrancar con ningún modelo")
        # Después y no a la vez: el repuesto tiene que salir con el modelo y el
        # esfuerzo que el primero acabó aceptando.
        proceso._preparar_repuesto()
        return proceso

    def _comando(self, log_path: Path | None = None) -> list[str]:
        comando = [self._binary, "--input-format", "stream-json",
                   "--output-format", "stream-json"]
        if self._model:
            comando += ["--model", self._model]
        if self._effort and not self._model.endswith(SUFIJOS_DE_ESFUERZO):
            comando += ["--effort", self._effort]
        # Nadie contesta a una petición de permiso en este modo: se deniega y
        # el turno sigue sin la herramienta. Es la misma decisión que con el
        # pseudoterminal —ver `agy_process.AgyProcess.start`—.
        comando += [
            "--dangerously-skip-permissions",
            "--log-file", str(log_path or self.log_path),
        ]
        # `--print` pide su valor pegado; vacío, el prompt llega por la entrada.
        comando += ["--print="]
        return comando

    def _lanzar(self, timeout: float) -> _Conexion:
        """Arranca un `agy` y espera a su `init`. No lo pone a atender."""
        os.makedirs(self._workspace, exist_ok=True)
        log_path = _nuevo_log()
        try:
            popen = subprocess.Popen(
                self._comando(log_path),
                cwd=self._workspace,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # Lo que `agy` dice al fallar antes del `init` solo sale por
                # aquí: sin guardarlo, un arranque roto no deja ni el motivo.
                stderr=open(log_path.with_suffix(".stderr"), "w", encoding="utf-8"),
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as error:
            raise AgyUnavailable(f"no se pudo lanzar {self._binary}: {error}") from error
        conexion = _Conexion(popen, log_path)
        threading.Thread(target=self._leer, args=(conexion,), daemon=True).start()
        if not conexion.listo.wait(timeout) or not conexion.conversation_id:
            self._matar(popen)
            error = self._ultimo_error(conexion)
            raise AgyUnavailable(
                "agy no llegó a arrancar en modo stream-json"
                + (f": {error}" if error else "")
            )
        return conexion

    def _estrenar(self, conexion: _Conexion) -> None:
        """Pone a atender una conexión ya arrancada."""
        self._actual = conexion
        self.conocidas.append(conexion.conversation_id)
        self._reservada = False
        log.info("agy listo (stream-json), conversación %s", conexion.conversation_id)

    def _preparar_repuesto(self) -> None:
        """Arranca en segundo plano el `agy` que atenderá la conversación siguiente."""
        if not self._con_repuesto:
            return
        with self._lock_repuesto:
            if self._cerrado or self._repuesto is not None or (
                self._preparando is not None and self._preparando.is_alive()
            ):
                return
            hilo = threading.Thread(target=self._arrancar_repuesto, daemon=True)
            self._preparando = hilo
        hilo.start()

    def _arrancar_repuesto(self) -> None:
        try:
            conexion = self._lanzar(ARRANQUE_TIMEOUT)
        except AgyUnavailable as error:
            # Sin repuesto se sigue funcionando: la conversación siguiente
            # arranca el suyo como antes.
            log.warning("No se pudo dejar un agy de repuesto: %s", error)
            return
        with self._lock_repuesto:
            if not self._cerrado:
                self._repuesto = conexion
                return
        # Lo cerraron mientras arrancaba: nadie va a usarlo.
        self._descartar(conexion)

    def _tomar_repuesto(self, esperar: bool) -> _Conexion | None:
        """El repuesto, si hay uno vivo. Con `esperar`, aguarda al que esté arrancando."""
        hilo = self._preparando
        if esperar and hilo is not None and hilo.is_alive():
            # Ya lleva un rato arrancando: esperarlo es más corto que lanzar
            # otro desde cero.
            hilo.join(ARRANQUE_TIMEOUT)
        with self._lock_repuesto:
            conexion, self._repuesto = self._repuesto, None
        if conexion is not None and not conexion.viva():
            self._descartar(conexion)
            return None
        return conexion

    def _descartar(self, conexion: _Conexion | None, conservar_log: bool = False) -> None:
        if conexion is None:
            return
        self._matar(conexion.popen)
        if conservar_log:
            _guardar_log_caido(conexion.log_path)
            return
        for ruta in (conexion.log_path, conexion.stderr_path):
            try:
                ruta.unlink(missing_ok=True)
            except OSError:
                pass

    def _ultimo_error(self, conexion: _Conexion) -> str:
        try:
            lineas = conexion.stderr_path.read_text(encoding="utf-8").strip().splitlines()
        except OSError:
            return ""
        # La línea del error, no la última: detrás suele venir la lista de
        # modelos disponibles, que no dice qué ha fallado.
        errores = [l for l in lineas if l.lower().startswith("error")]
        return (errores or lineas or [""])[0][:300]

    @staticmethod
    def _leer(conexion: _Conexion) -> None:
        eventos, listo = conexion.eventos, conexion.listo
        try:
            for linea in conexion.popen.stdout:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    evento = json.loads(linea)
                except json.JSONDecodeError:
                    continue
                if evento.get("event") == "init":
                    conexion.conversation_id = str(
                        evento.get("conversation_id")
                        or (evento.get("init") or {}).get("conversation_id")
                        or uuid.uuid4().hex
                    )
                    listo.set()
                    continue
                paso = evento.get("step_update") or {}
                if paso.get("step_type") == "user_input" and paso.get("state") == "DONE":
                    conexion.entradas += 1
                if not conexion.conversation_id:
                    conexion.conversation_id = str(paso.get("conversation_id") or "")
                    listo.set()
                eventos.put(evento)
        except (OSError, ValueError):
            pass
        finally:
            listo.set()
            eventos.put(_FIN)

    # --- La forma de `AgyProcess` ---

    def type(self, texto: str) -> None:
        if texto.strip() == "/new":
            with self._lock:
                if not self._reservada and self.entradas == 0 and self.alive():
                    # Recién arrancado y sin estrenar: su conversación ya es
                    # nueva. Cambiarlo serían décimas para acabar igual.
                    self._reservada = True
                    return
                # En este modo cada proceso es una conversación: la nueva es
                # otro, y a ser posible el que ya estaba arrancado esperando.
                vieja = self._actual
                nueva = self._tomar_repuesto(esperar=True)
                if nueva is None:
                    self._matar(vieja.popen)
                    nueva = self._lanzar(ARRANQUE_TIMEOUT)
                self._estrenar(nueva)
                self._reservada = True
            # La vieja se cierra fuera del candado y sin esperarla: puede
            # tardar hasta cinco segundos en irse y el turno ya tiene con quién.
            threading.Thread(target=self._descartar, args=(vieja,), daemon=True).start()
            self._preparar_repuesto()
            return
        popen = self._popen
        if popen is None or popen.stdin is None or popen.poll() is not None:
            raise AgyUnavailable("agy no está en marcha")
        try:
            popen.stdin.write(mensaje(texto))
            popen.stdin.flush()
        except (OSError, ValueError) as error:
            raise AgyUnavailable(f"agy no acepta el turno: {error}") from error

    def cortar(self) -> None:
        """Corta el turno en curso, que en este modo es cerrar su `agy`.

        Si hay repuesto listo pasa a atender él, sin estrenar, y el proceso
        sigue sano: el turno siguiente pide `/new`, se lo encuentra nuevo y no
        paga ningún arranque. Sin repuesto queda muerto, como antes, y el motor
        lo relanza entero.
        """
        with self._lock:
            vieja = self._actual
            nueva = self._tomar_repuesto(esperar=False)
            if nueva is not None:
                self._estrenar(nueva)
        # Su log se guarda: es el único sitio donde consta hasta dónde llegó.
        self._descartar(vieja, conservar_log=True)
        if nueva is not None:
            self._preparar_repuesto()

    def alive(self) -> bool:
        return self._actual.viva()

    def draining(self) -> bool:
        return self.alive()

    def healthy(self, *_args, **_kwargs) -> bool:
        return self.alive()

    def kill(self, conservar_log: bool = False) -> None:
        with self._lock_repuesto:
            self._cerrado = True
            repuesto, self._repuesto = self._repuesto, None
        self._descartar(repuesto)
        self._descartar(self._actual, conservar_log=conservar_log)

    @staticmethod
    def _matar(popen) -> None:
        if popen is None or popen.poll() is not None:
            return
        try:
            popen.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        popen.terminate()
        try:
            popen.wait(timeout=5)
        except subprocess.TimeoutExpired:
            popen.kill()

    def cliente(self) -> "AgyStreamClient":
        return AgyStreamClient(self)


class AgyStreamClient:
    """La forma de `AgyClient`, sobre los eventos del proceso."""

    def __init__(self, proceso: AgyStreamProcess) -> None:
        self.proceso = proceso

    def conversations(self) -> list[str]:
        conocidas = list(self.proceso.conocidas)
        if not self.proceso._reservada and conocidas:
            conocidas.remove(self.proceso.conversation_id)
        return conocidas

    def user_input_count(self, cascade_id: str) -> int:
        if cascade_id != self.proceso.conversation_id:
            return 0
        return self.proceso.entradas

    def stop(self, cascade_id: str) -> None:
        # No hay otra forma de cortar un turno en este modo.
        self.proceso.cortar()

    def stream_updates(
        self, cascade_id: str, timeout: float = 300.0, skip_text: str = ""
    ) -> Iterator[agy_client.Update]:
        if cascade_id != self.proceso.conversation_id:
            raise agy_client.AgyError("esa conversación ya no es la de este agy")
        eventos = self.proceso._eventos
        # Lo que quedara de un turno anterior no es de este.
        while True:
            try:
                sobrante = eventos.get_nowait()
            except queue.Empty:
                break
            if sobrante is _FIN:
                raise agy_client.AgyError("agy se ha cerrado")
        return self._seguir(eventos, timeout)

    def _seguir(self, eventos: queue.Queue, timeout: float) -> Iterator[agy_client.Update]:
        traductor = Traductor()
        fin = time.monotonic() + timeout
        while True:
            restante = fin - time.monotonic()
            if restante <= 0:
                return
            try:
                evento = eventos.get(timeout=restante)
            except queue.Empty:
                return
            if evento is _FIN:
                raise agy_client.AgyError("agy se cerró a mitad del turno")
            if evento.get("event") == "result":
                resultado = evento.get("result") or {}
                if resultado.get("status") == "ERROR" and not traductor.texto:
                    raise agy_client.AgyError(
                        f"agy terminó el turno con error: {resultado.get('error') or '?'}"
                    )
                if not traductor.texto and resultado.get("response"):
                    traductor.texto = str(resultado["response"])
                yield traductor.final()
                return
            paso = evento.get("step_update")
            if isinstance(paso, dict):
                update = traductor.paso(paso)
                if update is not None:
                    yield update

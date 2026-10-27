"""La voz de Codex como voz de la cara.

Codex lleva la conversación hablada —escucha, contesta y se le puede
interrumpir— y Vibi sigue haciendo el trabajo: todo lo que no es charla pasa
por `vibi_request`, que entra por el mismo `procesar_mensaje` que un turno de
voz de los de siempre, con su motor, su historial y sus permisos.

El audio no pasa por aquí. El navegador negocia WebRTC directamente con
OpenAI; este módulo solo le hace de intermediario para la oferta SDP y atiende
las herramientas que Codex llama. Usa la sesión de ChatGPT que guarda la propia
CLI de Codex: no hay clave de API ni credenciales que copiar.

La superficie realtime del app-server es experimental. Validada con la 0.161.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

VOCES = ("juniper", "maple", "breeze")
VOZ_PREDETERMINADA = "maple"

# Lo que puede pasar sin que la cara pregunte por eventos antes de darla por
# muerta. La cara pregunta cada segundo y medio; un cierre de golpe no avisa.
SIN_LATIDO_S = 30

# Cuando OpenAI dice que se ha agotado el cupo de voz de la cuenta, cada
# llamada nueva conecta y se corta a los quince segundos. Mientras dure esta
# espera la cara va directa a la voz de siempre en vez de repetir el corte.
ESPERA_TRAS_LIMITE_S = 30 * 60
_limite_hasta = 0.0

# El core arranca desde el instalador o desde la app, con un PATH que no
# siempre incluye Homebrew. Estos son los sitios donde suele estar la CLI.
_CANDIDATOS = (
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
    str(Path.home() / ".local" / "bin" / "codex"),
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
)

INSTRUCCIONES = """Eres Vibi, la asistente personal del usuario. Hablas en español, breve y natural.
Para cualquier petición sobre su ordenador, dispositivos, archivos, skills, tareas, recordatorios o programación, usa vibi_request con la petición completa.
Vibi ejecuta esas peticiones con su motor configurado. Tú no programas, no usas terminal, archivos locales ni navegador, y no cambias de motor.
Antes de llamar a vibi_request di una frase corta como «ahora lo miro», para que no haya silencio.
No anuncies éxito hasta recibir el resultado. Al recibirlo, cuéntalo por voz sin inventar acciones ni resultados.
Si hay una aprobación pendiente, explícalo; nunca apruebes por el usuario.
La charla informal puedes resolverla tú directamente.
Cuando el usuario se despida o diga que ya está («adiós», «gracias, eso es todo»), despídete en una frase y llama a terminar_conversacion."""

HERRAMIENTAS = [
    {
        "type": "function",
        "name": "vibi_request",
        "description": (
            "Envía la petición del usuario a su Vibi. Vibi gestiona equipos, "
            "archivos, skills, tareas y programación con sus motores, y "
            "conserva sus permisos y aprobaciones."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"request": {"type": "string"}},
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "terminar_conversacion",
        "description": "Cierra la conversación de voz cuando el usuario se despide.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]

Delegar = Callable[[str, str], dict]


class CodexNoDisponible(RuntimeError):
    """No hay Codex con el que hablar: la cara vuelve a la voz de siempre."""


def ejecutable() -> str | None:
    propio = os.environ.get("VIBI_CODEX_BIN")
    if propio:
        return propio if Path(propio).is_file() else None
    encontrado = shutil.which("codex")
    if encontrado:
        return encontrado
    return next((c for c in _CANDIDATOS if Path(c).is_file()), None)


def validar_voz(voz: str) -> str:
    if voz not in VOCES:
        raise ValueError("Elige Juniper, Maple o Breeze")
    return voz


def _texto(resultado: dict) -> dict:
    return {"type": "inputText", "text": json.dumps(resultado, ensure_ascii=False)[:8000]}


class SesionVoz:
    """Un app-server de Codex por conversación de voz."""

    def __init__(self, conversation_id: str, delegar: Delegar, binario: str):
        env = os.environ.copy()
        # Con una clave en el entorno Codex la preferiría a la sesión de
        # ChatGPT, y la voz se cobraría por API sin que nadie lo hubiera pedido.
        for nombre in ("OPENAI_API_KEY", "CODEX_API_KEY"):
            env.pop(nombre, None)
        self.proceso = subprocess.Popen(
            [binario, "app-server", "--listen", "stdio://",
             "--disable", "shell_tool", "--disable", "plugins",
             "--disable", "remote_plugin"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.conversation_id = conversation_id
        self.delegar = delegar
        self.cwd = Path(tempfile.gettempdir()) / "vibi-codex-voz"
        self.cwd.mkdir(exist_ok=True)
        self.pendientes: dict[int, queue.Queue] = {}
        self.eventos: list[dict] = []
        self.contador = 0
        self.lock = threading.RLock()
        self.lock_escritura = threading.Lock()
        self.respuesta_sdp: queue.Queue = queue.Queue(maxsize=1)
        self.thread_id: str | None = None
        self.cerrada = False
        self.parando = threading.Event()
        self.ultimo_latido = time.monotonic()
        self.resultados: dict[str, dict] = {}
        self.lock_herramientas = threading.Lock()
        threading.Thread(target=self._leer, daemon=True).start()

    # -- canal con el app-server ------------------------------------------

    def _emitir(self, evento: dict) -> None:
        with self.lock:
            self.eventos.append(evento)
            self.eventos = self.eventos[-150:]

    def recoger(self) -> list[dict]:
        self.ultimo_latido = time.monotonic()
        with self.lock:
            eventos, self.eventos = self.eventos, []
        return eventos

    def _escribir(self, mensaje: dict) -> None:
        with self.lock_escritura:
            if self.cerrada or self.proceso.poll() is not None:
                raise RuntimeError("La sesión de Codex está cerrada")
            self.proceso.stdin.write(json.dumps(mensaje) + "\n")
            self.proceso.stdin.flush()

    def _llamar(self, metodo: str, params: dict, timeout: float = 55) -> dict:
        with self.lock:
            self.contador += 1
            identificador = self.contador
            destino = self.pendientes[identificador] = queue.Queue(maxsize=1)
        try:
            self._escribir({"id": identificador, "method": metodo, "params": params})
            try:
                respuesta = destino.get(timeout=timeout)
            except queue.Empty:
                raise RuntimeError(f"Codex no respondió a tiempo ({metodo})") from None
            if "error" in respuesta:
                raise RuntimeError(respuesta["error"].get("message", "Error de Codex"))
            return respuesta.get("result", {})
        finally:
            with self.lock:
                self.pendientes.pop(identificador, None)

    def _herramienta(self, mensaje: dict) -> None:
        params = mensaje.get("params", {})
        call_id = str(params.get("callId") or "")
        with self.lock_herramientas:
            if call_id and call_id in self.resultados:
                resultado = self.resultados[call_id]
            else:
                resultado = self._atender(params, call_id or "sin-id")
                if call_id:
                    self.resultados[call_id] = resultado
        try:
            self._escribir({"id": mensaje["id"], "result": resultado})
        except (RuntimeError, OSError):
            pass

    def _atender(self, params: dict, call_id: str) -> dict:
        herramienta = params.get("tool")
        argumentos = params.get("arguments")
        if self.parando.is_set():
            return {"success": False, "contentItems": [_texto({"error": "La conversación ha terminado"})]}
        if herramienta == "terminar_conversacion":
            self._emitir({"type": "vibi/cerrar"})
            return {"success": True, "contentItems": [_texto({"ok": True})]}
        peticion = argumentos.get("request") if isinstance(argumentos, dict) else None
        if herramienta != "vibi_request" or not isinstance(peticion, str) or not peticion.strip():
            return {"success": False, "contentItems": [_texto({"error": "Herramienta o argumentos no válidos"})]}
        self._emitir({"type": "vibi/request", "text": peticion[:2000]})
        try:
            resultado = self.delegar(peticion.strip()[:12000], call_id)
            exito = "error" not in resultado
        except Exception as error:  # Lo que falle se le cuenta a Codex, no se tumba la llamada.
            log.warning("La voz de Codex no pudo delegar en Vibi: %s", error)
            resultado, exito = {"error": str(error)[:2000] or "Vibi no pudo atender la petición"}, False
        self._emitir({"type": "vibi/result", "success": exito})
        return {"success": exito, "contentItems": [_texto(resultado)]}

    def _leer(self) -> None:
        try:
            for linea in self.proceso.stdout:
                try:
                    mensaje = json.loads(linea)
                except ValueError:
                    continue
                if "id" in mensaje and ("result" in mensaje or "error" in mensaje):
                    with self.lock:
                        destino = self.pendientes.get(mensaje["id"])
                    if destino:
                        destino.put_nowait(mensaje)
                    continue
                metodo = mensaje.get("method", "")
                params = mensaje.get("params", {})
                if "id" in mensaje:
                    if metodo == "item/tool/call":
                        threading.Thread(target=self._herramienta, args=(mensaje,), daemon=True).start()
                    else:
                        # Aprobaciones y demás peticiones del app-server: las
                        # decisiones se toman en Vibi, nunca desde la voz.
                        try:
                            self._escribir({"id": mensaje["id"], "error": {
                                "code": -32601, "message": "Usa las herramientas y aprobaciones de Vibi"}})
                        except (RuntimeError, OSError):
                            pass
                    continue
                if metodo == "thread/realtime/sdp":
                    self._responder_sdp({"sdp": params.get("sdp", "")})
                elif metodo == "thread/realtime/error":
                    mensaje_error = str(params.get("message") or "Error de voz")[:1000]
                    log.warning("Voz de Codex: %s", mensaje_error)
                    if "usage limit" in mensaje_error.lower():
                        _marcar_limite()
                    self._responder_sdp({"error": mensaje_error})
                    self._emitir({"type": "error", "message": mensaje_error})
                elif metodo == "thread/realtime/closed":
                    log.info("Voz de Codex: la llamada se ha cerrado (%s)", params.get("reason", ""))
                    self._emitir({"type": "closed"})
        finally:
            self._emitir({"type": "closed"})
            with self.lock:
                for destino in self.pendientes.values():
                    try:
                        destino.put_nowait({"error": {"message": "Se cerró el proceso de Codex"}})
                    except queue.Full:
                        pass

    def _responder_sdp(self, respuesta: dict) -> None:
        try:
            self.respuesta_sdp.put_nowait(respuesta)
        except queue.Full:
            pass

    # -- ciclo de vida -----------------------------------------------------

    def arrancar(self, sdp: str, voz: str) -> str:
        self._llamar("initialize", {
            "clientInfo": {"name": "vibi", "title": "Vibi", "version": "1"},
            "capabilities": {"experimentalApi": True},
        })
        self._escribir({"method": "initialized"})
        cuenta = self._llamar("account/read", {"refreshToken": False}).get("account") or {}
        if cuenta.get("type") != "chatgpt":
            raise CodexNoDisponible("Codex no tiene sesión de ChatGPT. Ejecuta `codex login`.")
        hilo = self._llamar("thread/start", {
            "cwd": str(self.cwd), "ephemeral": True, "sandbox": "read-only",
            "approvalPolicy": "never", "baseInstructions": INSTRUCCIONES,
            "dynamicTools": HERRAMIENTAS,
            "config": {"mcp_servers": {}, "features": {
                "shell_tool": False, "plugins": False, "remote_plugin": False}},
        })
        self.thread_id = hilo["thread"]["id"]
        self._llamar("thread/realtime/start", {
            "threadId": self.thread_id, "outputModality": "audio",
            "voice": validar_voz(voz), "includeStartupContext": True,
            "clientManagedHandoffs": False, "version": "v3",
            "transport": {"type": "webrtc", "sdp": sdp},
        })
        try:
            respuesta = self.respuesta_sdp.get(timeout=55)
        except queue.Empty:
            raise RuntimeError("No llegó la negociación de voz") from None
        if "error" in respuesta:
            raise RuntimeError(respuesta["error"])
        self.ultimo_latido = time.monotonic()
        return respuesta["sdp"]

    def cerrar(self) -> None:
        if self.parando.is_set():
            return
        self.parando.set()
        try:
            if self.thread_id and self.proceso.poll() is None:
                self._llamar("thread/realtime/stop", {"threadId": self.thread_id}, timeout=4)
        except Exception:
            pass
        self.cerrada = True
        if self.proceso.poll() is None:
            self.proceso.terminate()
            try:
                self.proceso.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proceso.kill()
                self.proceso.wait(timeout=4)


# -- registro: una llamada por usuario ----------------------------------------

_sesiones: dict[object, SesionVoz] = {}
_lock = threading.Lock()
_vigia: threading.Thread | None = None


def _vigilar() -> None:
    while True:
        time.sleep(5)
        with _lock:
            caducadas = [
                (usuario, sesion) for usuario, sesion in _sesiones.items()
                if time.monotonic() - sesion.ultimo_latido > SIN_LATIDO_S
            ]
            for usuario, _ in caducadas:
                _sesiones.pop(usuario, None)
        for _, sesion in caducadas:
            log.info("Voz de Codex sin latido: se cierra")
            sesion.cerrar()


def _marcar_limite() -> None:
    global _limite_hasta
    _limite_hasta = time.monotonic() + ESPERA_TRAS_LIMITE_S


def abrir(usuario: object, conversation_id: str, sdp: str, voz: str, delegar: Delegar) -> str:
    """Abre la llamada y devuelve la respuesta SDP. Bloquea: va en un hilo."""
    global _vigia
    validar_voz(voz)
    if time.monotonic() < _limite_hasta:
        raise CodexNoDisponible("Se ha agotado el límite de voz de la cuenta de ChatGPT.")
    binario = ejecutable()
    if not binario:
        raise CodexNoDisponible("No encuentro Codex CLI en este ordenador.")
    cerrar(usuario)
    sesion = SesionVoz(conversation_id, delegar, binario)
    with _lock:
        _sesiones[usuario] = sesion
        if _vigia is None:
            _vigia = threading.Thread(target=_vigilar, daemon=True)
            _vigia.start()
    try:
        return sesion.arrancar(sdp, voz)
    except Exception:
        cerrar(usuario, conversation_id)
        raise


def eventos(usuario: object, conversation_id: str) -> tuple[bool, list[dict]]:
    with _lock:
        sesion = _sesiones.get(usuario)
    if not sesion or sesion.conversation_id != conversation_id:
        return False, []
    pendientes = sesion.recoger()
    return not sesion.cerrada and sesion.proceso.poll() is None, pendientes


def cerrar(usuario: object, conversation_id: str | None = None) -> bool:
    with _lock:
        sesion = _sesiones.get(usuario)
        if not sesion or (conversation_id and sesion.conversation_id != conversation_id):
            return False
        _sesiones.pop(usuario, None)
    sesion.cerrar()
    return True


def cerrar_todas() -> None:
    with _lock:
        sesiones = list(_sesiones.values())
        _sesiones.clear()
    for sesion in sesiones:
        sesion.cerrar()

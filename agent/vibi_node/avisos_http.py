"""La puerta por la que cualquier proceso de esta máquina avisa a Vibi.

`notifications_windows` lee lo que el sistema ya decidió enseñar en su centro
de notificaciones. Esto es la otra mitad: un proceso que quiere avisar y no
tiene por qué pasar por el sistema operativo —un hook de una herramienta de
terminal, un script, un cron— hace un POST aquí y el aviso entra por el mismo
camino que los demás.

**Por qué hace falta.** Una CLI que termina no publica un toast: emite una
secuencia de escape (BEL, OSC 9) y es el terminal quien decide si eso se
convierte en notificación del sistema. iTerm2 y Ghostty lo hacen; Windows
Terminal no. Así que lo que se ve en el centro de notificaciones depende del
terminal que tengas abierto, y eso no es una base sobre la que construir.

**Sin credencial, y a propósito.** Escucha solo en 127.0.0.1: quien puede
llamar aquí ya está dentro de la máquina, donde `system_shell` le da una shell
entera. Un token protegería de nadie. Es el mismo criterio que el MCP del
navegador y el contrario que `system_mcp`, que sí lo lleva porque sirve el
disco y puede escuchar fuera de localhost.

**El servidor vive lo que vive el agente, no lo que vive la conexión.** El
socket se abre una vez y se queda; lo que se registra y se olvida en cada
sesión es a dónde reenviar. Reabrir el puerto en cada reconexión sería pelearse
con el TIME_WAIT del anterior por nada. Si en ese momento no hay conexión con
Vibi, el POST se responde con 503 en vez de encolarse: quien avisa se entera de
que no llegó, que es más útil que un sí que no era verdad.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

log = logging.getLogger("vibi.node.avisos_http")

PUERTO_POR_DEFECTO = 8933

# Nunca fuera de esta máquina: ver el docstring del módulo.
HOST = "127.0.0.1"

# Lo que se espera a que el envío llegue al hilo del agente. Es holgado para lo
# que cuesta —mandar por un WebSocket ya abierto— y corto para quien llama, que
# suele ser un hook bloqueando el final de otro programa.
TIMEOUT_ENVIO = 5.0

# Lo máximo que se acepta de cada campo. El servidor recorta igual al sanear;
# esto solo evita que un proceso local llene la memoria del nodo antes.
MAX_CAMPO = 1_000

_servidor = None  # uvicorn.Server
_hilo: threading.Thread | None = None
_puerto: int = 0

_destino: tuple[object, asyncio.AbstractEventLoop] | None = None
_candado = threading.Lock()


def registrar(connection, loop: asyncio.AbstractEventLoop) -> None:
    """Dice a dónde mandar lo que llegue, mientras dure esta sesión."""
    global _destino
    with _candado:
        _destino = (connection, loop)


def olvidar() -> None:
    """La sesión se acabó: lo que llegue ahora se rechaza hasta que haya otra."""
    global _destino
    with _candado:
        _destino = None


def _entregar(aviso: dict) -> bool:
    """Manda el aviso por la conexión de la sesión. Devuelve si llegó.

    Corre en el hilo del servidor HTTP y la conexión vive en el del agente, así
    que el envío se cruza con `run_coroutine_threadsafe`: un objeto de asyncio
    no se toca desde otro hilo.
    """
    with _candado:
        destino = _destino
    if destino is None:
        return False

    connection, loop = destino
    mensaje = json.dumps({"tipo": "aviso", "aviso": aviso})
    try:
        futuro = asyncio.run_coroutine_threadsafe(connection.send(mensaje), loop)
        futuro.result(timeout=TIMEOUT_ENVIO)
    except Exception as error:  # noqa: BLE001 - la conexión se cayó o tardó
        log.warning("No pude entregar un aviso local: %s", error)
        return False
    return True


def _campo(crudo: object) -> str:
    return " ".join(str(crudo or "").split())[:MAX_CAMPO]


CAMPOS = ("app", "titulo", "cuerpo")

# Lo más grande que se lee de una petición. Un aviso son tres frases; lo que
# pase de aquí es un error de quien llama o alguien probando suerte.
MAX_CUERPO_HTTP = 64 * 1024


def _resolver(crudo: bytes) -> tuple[int, dict]:
    """De los bytes de la petición a la respuesta. Sin tocar red: así se prueba.

    Los rechazos llevan motivo porque al otro lado hay un script, no una
    persona: un 400 a secas le deja adivinando si el aviso salió o no.
    """
    try:
        entrante = json.loads(crudo or b"{}")
    except ValueError:
        return 400, {"entregado": False, "motivo": "El cuerpo no es JSON válido."}
    if not isinstance(entrante, dict):
        return 400, {"entregado": False, "motivo": "Se espera un objeto JSON."}

    sobra = sorted(set(entrante) - set(CAMPOS))
    if sobra:
        # Cerrado a propósito: si alguien manda `mensaje` en vez de `cuerpo`,
        # es mejor que se entere ahora y no que su aviso desaparezca callado.
        return 400, {
            "entregado": False,
            "motivo": f"Campos que no existen: {', '.join(sobra)}. "
            f"Solo hay {', '.join(CAMPOS)}.",
        }

    aviso = {campo: _campo(entrante.get(campo)) for campo in CAMPOS}
    if not aviso["titulo"] and not aviso["cuerpo"]:
        return 400, {"entregado": False, "motivo": "Hace falta `titulo` o `cuerpo`."}
    if not _entregar(aviso):
        return 503, {
            "entregado": False,
            "motivo": "Ahora mismo no hay conexión con Vibi.",
        }
    return 200, {"entregado": True}


def _construir_app():
    """Una app ASGI a mano, sin framework.

    Es una ruta que recibe tres cadenas: meter FastAPI para esto añadiría una
    dependencia que el agente no declara —solo declara `uvicorn`, y a propósito—
    a cambio de nada que aquí se use.
    """

    async def aplicacion(scope, receive, send):
        if scope["type"] != "http":
            return

        cuerpo, pasado = b"", False
        while True:
            evento = await receive()
            if evento["type"] != "http.request":
                break
            cuerpo += evento.get("body", b"")
            if len(cuerpo) > MAX_CUERPO_HTTP:
                pasado = True
                break
            if not evento.get("more_body"):
                break

        if scope["path"].rstrip("/") != "/aviso":
            estado, respuesta = 404, {"entregado": False, "motivo": "No existe."}
        elif scope["method"] != "POST":
            estado, respuesta = 405, {"entregado": False, "motivo": "Usa POST."}
        elif pasado:
            estado, respuesta = 413, {
                "entregado": False,
                "motivo": "Un aviso son tres frases, no un archivo.",
            }
        else:
            # `_resolver` espera al hilo del agente para entregar, así que no
            # puede correr en el bucle de uvicorn: lo bloquearía entero.
            estado, respuesta = await asyncio.to_thread(_resolver, cuerpo)

        crudo = json.dumps(respuesta).encode()
        await send(
            {
                "type": "http.response.start",
                "status": estado,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(crudo)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": crudo})

    return aplicacion


def _vivo() -> bool:
    return _hilo is not None and _hilo.is_alive()


def arrancar(puerto: int = PUERTO_POR_DEFECTO) -> int:
    """Deja el servidor escuchando y devuelve en qué puerto. Idempotente."""
    global _servidor, _hilo, _puerto

    if _vivo():
        return _puerto

    import uvicorn  # noqa: PLC0415 - solo hace falta al levantar el servidor

    class _Servidor(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            # Igual que en `system_mcp`: registrar señales solo vale desde el
            # hilo principal y esto corre en uno propio.
            return

    configuracion = uvicorn.Config(
        _construir_app(),
        host=HOST,
        port=puerto,
        log_level="warning",
        access_log=False,
    )
    _servidor = _Servidor(configuracion)
    _hilo = threading.Thread(target=_servidor.run, name="vibi-avisos-http", daemon=True)
    _hilo.start()
    _puerto = puerto
    log.info("Escuchando avisos locales en http://%s:%d/aviso", HOST, puerto)
    return puerto

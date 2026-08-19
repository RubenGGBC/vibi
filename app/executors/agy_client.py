"""Cliente del language server que `agy` levanta en localhost.

La CLI de Antigravity no es un programa monolítico: arranca dentro de sí un
servidor y le habla por Connect RPC. Ese servidor acepta JSON plano y no pide
credenciales, así que Vibi puede usarlo igual que lo usa la propia CLI, sin
parsear pantallas ni el SQLite interno.

Es formato interno de Google y `agy` se actualiza solo, así que esto puede
romperse con una versión nueva. Cuando pase, las llamadas devolverán un error
legible y el turno se irá a Claude.
"""
from __future__ import annotations

import json
import logging
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import Iterator

log = logging.getLogger("vibi.agy")

SERVICE = "exa.language_server_pb.LanguageServerService"

STEP_PLANNER_RESPONSE = "CORTEX_STEP_TYPE_PLANNER_RESPONSE"
STATUS_DONE = "CORTEX_STEP_STATUS_DONE"

# Los pasos que forman el andamiaje del turno. Todo lo demás que aparezca es
# una herramienta: `LIST_DIRECTORY`, `SEARCH_WEB` y las que vengan, que no hay
# lista cerrada y no conviene inventarla.
PASOS_DE_ANDAMIAJE = frozenset({
    STEP_PLANNER_RESPONSE,
    "CORTEX_STEP_TYPE_USER_INPUT",
    "CORTEX_STEP_TYPE_CONVERSATION_HISTORY",
    "CORTEX_STEP_TYPE_CHECKPOINT",
    # `GENERIC` tampoco es una herramienta, y colarse aquí le costaba a Vibi
    # el turno entero: llega en `RUNNING` y nadie manda nunca su `DONE`, así
    # que `_hay_herramientas_a_medias` decía que sí para siempre y el turno no
    # cerraba jamás. La respuesta estaba escrita y cerrada, pero Vibi seguía
    # esperando hasta agotar los 60 s de silencio y se la pasaba a Claude.
    #
    # Comprobado contra el `agy` real el 19/08/2026 con un «echo hola»: el
    # comando se ejecutó, el paso de respuesta quedó DONE con «hola» dentro, y
    # el turno cayó igualmente. Son 20 de las 47 caídas reales, y ninguna era
    # de Google como parecía por los `streamGenerateContent` del log.
    #
    # El resto de tipos que existen sí nombran una acción —`RUN_COMMAND`,
    # `VIEW_FILE`, `SEARCH_WEB`, `BROWSER_CLICK_ELEMENT`—: los 55 que declara
    # el binario se leen con
    # `strings agy.exe | grep -oE "CORTEX_STEP_TYPE_[A-Z_]+"`.
    "CORTEX_STEP_TYPE_GENERIC",
})
ESTADOS_EN_CURSO = frozenset({
    "CORTEX_STEP_STATUS_PENDING",
    "CORTEX_STEP_STATUS_RUNNING",
})


@dataclass(frozen=True)
class Update:
    """Lo único que a Vibi le interesa de una actualización del stream."""

    text: str | None = None
    done: bool = False
    # Herramientas nombradas en este mensaje, con el estado en que van. Sin
    # esto no se puede saber si un `done` cierra el turno o solo cierra la
    # frase con la que el modelo anuncia que va a mirar algo.
    herramientas: tuple[tuple[str, str], ...] = ()
    # Una trayectoria puede avanzar sin producir texto mientras ejecuta una
    # herramienta. Ese movimiento cuenta como señal de vida para el turno.
    activity: bool = False
    tools_running: bool = False


class AgyError(RuntimeError):
    """El language server no contestó lo que se esperaba."""


class AgyClient:
    """Habla con el language server de una instancia concreta de `agy`."""

    def __init__(self, port: int, timeout: float = 30.0) -> None:
        self.port = port
        self.timeout = timeout

    def _url(self, method: str) -> str:
        # 127.0.0.1 y no "localhost": en Windows resolver el nombre prueba
        # primero IPv6 y se come un timeout en cada llamada.
        return f"http://127.0.0.1:{self.port}/{SERVICE}/{method}"

    def _post(self, method: str, payload: dict) -> dict:
        request = urllib.request.Request(
            self._url(method),
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            detalle = error.read().decode("utf-8", "replace")[:300]
            raise AgyError(f"{method} devolvió {error.code}: {detalle}") from error
        except Exception as error:
            raise AgyError(f"{method} no respondió: {error}") from error

    def conversations(self) -> list[str]:
        """Los identificadores de las conversaciones que `agy` tiene abiertas."""
        data = self._post("GetAllCascadeTrajectories", {})
        return list((data.get("trajectorySummaries") or {}).keys())

    def stop(self, cascade_id: str) -> None:
        """Corta el turno en curso."""
        self._post("ForceStopCascadeTree", {"conversationId": cascade_id})

    def user_input_count(self, cascade_id: str) -> int:
        """Cuántos turnos del usuario ha registrado esta conversación."""
        data = self._post(
            "GetCascadeTrajectorySteps",
            {"cascadeId": cascade_id, "conversationId": cascade_id},
        )
        return sum(
            step.get("type") == "CORTEX_STEP_TYPE_USER_INPUT"
            for step in data.get("steps") or []
        )

    def stream_updates(
        self, cascade_id: str, timeout: float = 300.0, skip_text: str = ""
    ) -> Iterator[Update]:
        """Sigue el turno según lo va escribiendo el modelo.

        La conexión se abre aquí mismo, no al empezar a leer: quien llama
        teclea el turno justo después, y si el stream no estuviera ya
        escuchando se perdería el principio de la respuesta.

        `skip_text` es la respuesta del turno anterior. Hace falta porque al
        abrir el stream el servidor vuelca el estado actual, que la trae ya
        marcada como terminada: sin descartarla, el turno se cerraría antes de
        empezar repitiendo lo que Vibi ya había dicho.

        Termina cuando el paso de respuesta pasa a `DONE`, que es la señal
        buena: antes había que adivinarlo por el silencio en pantalla.
        """
        return self._iter_updates(
            self._open_stream(cascade_id, timeout), skip_text
        )

    def _open_stream(self, cascade_id: str, timeout: float):
        payload = json.dumps(
            {"cascadeId": cascade_id, "conversationId": cascade_id}
        ).encode()
        # Connect exige el sobre también en la petición.
        envelope = b"\x00" + struct.pack(">I", len(payload)) + payload
        request = urllib.request.Request(
            self._url("StreamAgentStateUpdates"),
            data=envelope,
            headers={
                "content-type": "application/connect+json",
                "connect-protocol-version": "1",
            },
        )
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            detalle = error.read().decode("utf-8", "replace")[:300]
            raise AgyError(f"el stream devolvió {error.code}: {detalle}") from error
        except Exception as error:
            raise AgyError(f"no se pudo abrir el stream: {error}") from error

    def _iter_updates(self, response, skip_text: str = "") -> Iterator[Update]:
        empezado = False
        # Comparado sin espacios de los bordes: la respuesta anterior se
        # guarda recortada y el stream no recorta, así que una respuesta que
        # terminara en salto de línea no se reconocía a sí misma. El eco se
        # colaba como respuesta buena y, al venir ya cerrado, cerraba el turno
        # al instante — y desde ahí la conversación entera iba un turno por
        # detrás, contestando siempre a la pregunta anterior.
        anterior = skip_text.strip()
        # Qué herramienta va por dónde. Un `done` en el paso de respuesta no
        # cierra el turno si hay alguna a medias: el modelo anuncia en voz alta
        # que va a mirar algo, cierra esa frase, ejecuta la herramienta y
        # sigue escribiendo después. Cerrar en ese primer `done` dejaba el
        # turno en «deja que lo mire» y mandaba la respuesta buena al turno
        # siguiente, con lo que la conversación entera quedaba desfasada.
        estado_herramientas: dict[str, str] = {}
        with response:
            for raw in read_envelopes(response):
                update = read_update(raw)
                estado_herramientas.update(update.herramientas)
                update = replace(
                    update,
                    tools_running=_hay_herramientas_a_medias(
                        estado_herramientas
                    ),
                )
                if update.text is None:
                    if update.activity:
                        yield update
                    continue
                if not empezado and anterior and update.text.strip() == anterior and update.done:
                    # El eco del turno anterior, no el principio de este.
                    #
                    # Lo que los distingue es el `done`, no el texto: el eco
                    # llega con su paso ya cerrado, mientras que la respuesta
                    # nueva siempre empieza abierta, aunque sea de una palabra
                    # —comprobado contra el `agy` real: hasta un «hecho» pasa
                    # por GENERATING antes de cerrarse—. Comparando solo el
                    # texto, contestar dos veces lo mismo descartaba también la
                    # respuesta buena y el turno no cerraba nunca.
                    #
                    # Y hay que seguir descartando mientras coincida, no solo
                    # el primero: el volcado inicial puede llegar repartido en
                    # varios mensajes, y dejar pasar el segundo cierra el turno
                    # con la respuesta anterior. Eso desfasa la conversación
                    # entera un turno, que es mucho peor que esperar de más.
                    continue
                empezado = True
                yield update
                if update.done and not _hay_herramientas_a_medias(estado_herramientas):
                    return


def _hay_herramientas_a_medias(estado: dict[str, str]) -> bool:
    """¿Queda alguna herramienta sin terminar en este turno?

    Solo cuentan las herramientas, no los pasos de andamiaje. El `CHECKPOINT`
    queda fuera a propósito: aparece también después de la última respuesta, y
    esperarlo dejaría el turno abierto para siempre.
    """
    return any(valor in ESTADOS_EN_CURSO for valor in estado.values())


class TurnText:
    """Lleva la cuenta de lo que ya se ha dicho en el turno.

    El stream reenvía la respuesta entera cada vez que crece, así que hay que
    quedarse solo con la parte nueva; si no, la cara locutaría lo mismo una y
    otra vez.
    """

    def __init__(self) -> None:
        self.full = ""

    def advance(self, text: str) -> str | None:
        """Lo que hay que decir de nuevo, o None si no hay nada."""
        if text == self.full:
            return None
        if text.startswith(self.full):
            nuevo = text[len(self.full) :]
        else:
            # El modelo reescribió lo anterior: no se puede recortar por delante.
            nuevo = text
        self.full = text
        return nuevo or None


def _steps(update: dict) -> list[dict]:
    trajectory = (update.get("update") or {}).get("mainTrajectoryUpdate") or {}
    return (trajectory.get("stepsUpdate") or {}).get("steps") or []


def read_update(update: dict) -> Update:
    """Traduce una actualización cruda a texto, herramientas y fin de turno.

    El servidor manda muchas que no son de la respuesta (metadatos del
    ejecutor, del generador, del proyecto). Todas esas se ignoran.
    """
    steps = _steps(update)
    herramientas = tuple(
        (step.get("type") or "", step.get("status") or "")
        for step in steps
        if step.get("type") and step.get("type") not in PASOS_DE_ANDAMIAJE
    )
    # De atrás hacia delante: al abrir el stream, el estado que vuelca trae
    # todos los turnos de la conversación, y el que interesa es el último.
    for step in reversed(steps):
        if step.get("type") != STEP_PLANNER_RESPONSE:
            continue
        response = step.get("plannerResponse") or {}
        # Mientras escribe llega en `modifiedResponse`; al cerrar, en `response`.
        text = response.get("modifiedResponse") or response.get("response")
        if text:
            return Update(
                text=text,
                done=step.get("status") == STATUS_DONE,
                herramientas=herramientas,
                activity=bool(steps),
            )
    return Update(herramientas=herramientas, activity=bool(steps))


def read_envelopes(stream) -> Iterator[dict]:
    """Va devolviendo los mensajes de un server-stream de Connect.

    Cada uno viene precedido de un byte de banderas y cuatro de longitud, así
    que no vale con leer líneas: hay que respetar la cabecera.
    """
    while True:
        header = stream.read(5)
        if len(header) < 5:
            return
        length = struct.unpack(">I", header[1:5])[0]
        payload = b""
        while len(payload) < length:
            chunk = stream.read(length - len(payload))
            if not chunk:
                return
            payload += chunk
        try:
            yield json.loads(payload or b"{}")
        except json.JSONDecodeError:
            return

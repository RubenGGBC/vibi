"""Cliente del language server que `agy` levanta en localhost.

La CLI de Antigravity no es un programa monolítico: arranca dentro de sí un
servidor y le habla por Connect RPC. Ese servidor acepta JSON plano y no pide
credenciales, así que Morgana puede usarlo igual que lo usa la propia CLI, sin
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
from dataclasses import dataclass
from typing import Iterator

log = logging.getLogger("morgana.agy")

SERVICE = "exa.language_server_pb.LanguageServerService"

STEP_PLANNER_RESPONSE = "CORTEX_STEP_TYPE_PLANNER_RESPONSE"
STEP_TOOL_CALL = "CORTEX_STEP_TYPE_TOOL_CALL"
STATUS_DONE = "CORTEX_STEP_STATUS_DONE"


@dataclass(frozen=True)
class Update:
    """Lo único que a Morgana le interesa de una actualización del stream."""

    text: str | None = None
    done: bool = False


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
        empezar repitiendo lo que Morgana ya había dicho.

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
        with response:
            for raw in read_envelopes(response):
                update = read_update(raw)
                if update.text is None:
                    continue
                if not empezado and skip_text and update.text == skip_text:
                    # Es el eco del turno anterior, no el principio de este.
                    continue
                empezado = True
                yield update
                if update.done:
                    return


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
    """Traduce una actualización cruda a texto y a si el turno ha acabado.

    El servidor manda muchas que no son de la respuesta (metadatos del
    ejecutor, del generador, del proyecto). Todas esas se ignoran.
    """
    # De atrás hacia delante: al abrir el stream, el estado que vuelca trae
    # todos los turnos de la conversación, y el que interesa es el último.
    for step in reversed(_steps(update)):
        if step.get("type") != STEP_PLANNER_RESPONSE:
            continue
        response = step.get("plannerResponse") or {}
        # Mientras escribe llega en `modifiedResponse`; al cerrar, en `response`.
        text = response.get("modifiedResponse") or response.get("response")
        if text:
            return Update(text=text, done=step.get("status") == STATUS_DONE)
    return Update()


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

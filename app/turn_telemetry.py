"""Tiempos de un turno medidos con reloj monotónico y sin contenido."""
from __future__ import annotations

import time
from collections.abc import Callable

ROUTES = frozenset({"fast_action", "agy", "fallback"})
STAGE_FIELDS = (
    "route_decision_ms",
    "session_health_ms",
    "stream_open_ms",
    "input_ack_ms",
    "time_to_first_text_ms",
    # Cuándo dejó de llegar texto. Restándolo del total sale la cola muda del
    # turno: lo que se espera con la respuesta ya entera en pantalla. Sin este
    # campo, `post_tool_ms` mezcla el modelo redactando —que no se puede
    # acelerar— con la espera al cierre del stream, que es tiempo tirado.
    "time_to_last_text_ms",
    "tool_running_ms",
    "node_dispatch_ms",
    "node_execution_ms",
    "post_tool_ms",
)


class TurnTelemetry:
    """Acumula únicamente campos permitidos; no acepta payload arbitrario."""

    def __init__(
        self,
        route: str,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if route not in ROUTES:
            raise ValueError(f"Ruta de turno desconocida: {route}")
        self._route = route
        self._clock = clock
        self._started = clock()
        self._values = {field: 0.0 for field in STAGE_FIELDS}

    @property
    def started_at(self) -> float:
        return self._started

    def set_route(self, route: str) -> None:
        if route not in ROUTES:
            raise ValueError(f"Ruta de turno desconocida: {route}")
        self._route = route

    def _require(self, field: str) -> None:
        if field not in self._values:
            raise KeyError(field)

    def set_ms(self, field: str, value: float | int) -> None:
        self._require(field)
        self._values[field] = max(0.0, float(value))

    def add_seconds(self, field: str, seconds: float) -> None:
        self._require(field)
        self._values[field] += max(0.0, float(seconds)) * 1000.0

    def measure_since(self, field: str, started_at: float) -> None:
        self.set_ms(field, (self._clock() - started_at) * 1000.0)

    def stamp_since_start(self, field: str) -> None:
        self.set_ms(field, (self._clock() - self._started) * 1000.0)

    def merge_engine_stages(self, payload: dict[str, str | int]) -> None:
        """Incorpora tramos internos sin aceptar su ruta, total ni enrutado."""
        for field in STAGE_FIELDS:
            if field == "route_decision_ms" or field not in payload:
                continue
            value = payload[field]
            if isinstance(value, (int, float)):
                self.set_ms(field, value)

    def finish(self) -> dict[str, str | int]:
        payload: dict[str, str | int] = {
            "route": self._route,
            **{field: round(value) for field, value in self._values.items()},
        }
        payload["total_ms"] = max(0, round((self._clock() - self._started) * 1000))
        return payload

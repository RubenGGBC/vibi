"""Métricas monotónicas sin contenido del turno."""
from __future__ import annotations

from unittest import TestCase

from app import turn_telemetry


class _Clock:
    def __init__(self, *values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


class MedirEtapas(TestCase):
    def test_calcula_milisegundos_con_reloj_monotonico(self):
        clock = _Clock(10.0, 10.0014, 10.2501, 10.3004)
        timing = turn_telemetry.TurnTelemetry(route="agy", clock=clock)

        timing.measure_since("route_decision_ms", 10.0)
        timing.stamp_since_start("time_to_first_text_ms")
        payload = timing.finish()

        self.assertEqual(payload["route"], "agy")
        self.assertEqual(payload["route_decision_ms"], 1)
        self.assertEqual(payload["time_to_first_text_ms"], 250)
        self.assertEqual(payload["total_ms"], 300)

    def test_acumula_varios_intervalos_de_herramienta(self):
        timing = turn_telemetry.TurnTelemetry(route="agy", clock=_Clock(1.0, 1.5))

        timing.add_seconds("tool_running_ms", 0.0124)
        timing.add_seconds("tool_running_ms", 0.0084)
        payload = timing.finish()

        self.assertEqual(payload["tool_running_ms"], 21)

    def test_las_etapas_ausentes_salen_a_cero(self):
        timing = turn_telemetry.TurnTelemetry(
            route="fast_action", clock=_Clock(2.0, 2.1)
        )

        payload = timing.finish()

        self.assertEqual(
            set(payload),
            {"route", "total_ms", *turn_telemetry.STAGE_FIELDS},
        )
        self.assertTrue(
            all(payload[field] == 0 for field in turn_telemetry.STAGE_FIELDS)
        )

    def test_rechaza_campos_y_rutas_inventadas(self):
        timing = turn_telemetry.TurnTelemetry(route="agy", clock=_Clock(1.0))

        with self.assertRaises(KeyError):
            timing.set_ms("user_text", "Abre Spotify")
        with self.assertRaises(ValueError):
            turn_telemetry.TurnTelemetry(route="texto_libre", clock=lambda: 1.0)

    def test_set_ms_normaliza_negativos_y_decimales(self):
        timing = turn_telemetry.TurnTelemetry(
            route="fallback", clock=_Clock(5.0, 5.01)
        )

        timing.set_ms("node_dispatch_ms", -4)
        timing.set_ms("node_execution_ms", 4.6)
        payload = timing.finish()

        self.assertEqual(payload["node_dispatch_ms"], 0)
        self.assertEqual(payload["node_execution_ms"], 5)

    def test_fusiona_etapas_del_motor_sin_pisar_el_enrutado_exterior(self):
        timing = turn_telemetry.TurnTelemetry(
            route="agy", clock=_Clock(5.0, 5.02)
        )
        timing.set_ms("route_decision_ms", 4)

        timing.merge_engine_stages(
            {
                "route": "agy",
                "route_decision_ms": 99_999,
                "session_health_ms": 12,
                "stream_open_ms": 8,
                "total_ms": 99_999,
            }
        )
        payload = timing.finish()

        self.assertEqual(payload["route_decision_ms"], 4)
        self.assertEqual(payload["session_health_ms"], 12)
        self.assertEqual(payload["stream_open_ms"], 8)
        self.assertEqual(payload["total_ms"], 20)


if __name__ == "__main__":
    import unittest

    unittest.main()

"""Concurrencia y salud del camino caliente de Antigravity."""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from app import turn_telemetry
from app.executors import agy_client, agy_process, antigravity_chat


class _HealthyProcess:
    def healthy(self, *args, **kwargs):
        return True

    def alive(self):
        return True

    def kill(self):
        return None


class ArranqueConcurrente(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        antigravity_chat._processes.clear()
        antigravity_chat._process_touch.clear()
        antigravity_chat._playwright_urls.clear()
        antigravity_chat._sistema_urls.clear()
        locks = getattr(antigravity_chat, "_process_locks", None)
        if locks is not None:
            locks.clear()

    async def asyncTearDown(self):
        antigravity_chat._processes.clear()
        antigravity_chat._process_touch.clear()
        antigravity_chat._playwright_urls.clear()
        antigravity_chat._sistema_urls.clear()

    async def test_dos_solicitudes_del_mismo_usuario_arrancan_un_solo_agy(self):
        entered = threading.Event()
        release = threading.Event()
        starts = []
        process = _HealthyProcess()

        def start(*args, **kwargs):
            starts.append((args, kwargs))
            entered.set()
            release.wait(2)
            return process

        user = {"id": "u", "nombre": "Ruben"}
        with (
            patch.object(antigravity_chat, "asegurar_playwright", AsyncMock(return_value="")),
            patch.object(
                antigravity_chat.system_link,
                "asegurar_sistema",
                AsyncMock(return_value=""),
            ),
            patch.object(antigravity_chat, "escribir_configuracion_mcp"),
            patch.object(antigravity_chat.agy_process.AgyProcess, "start", side_effect=start),
        ):
            first = asyncio.create_task(
                antigravity_chat._process_for(user, Path("workspace"))
            )
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            second = asyncio.create_task(
                antigravity_chat._process_for(user, Path("workspace"))
            )
            await asyncio.sleep(0.05)
            release.set()
            results = await asyncio.gather(first, second)

        self.assertEqual(len(starts), 1)
        self.assertIs(results[0], process)
        self.assertIs(results[1], process)

    async def test_playwright_y_pc_se_aseguran_en_paralelo(self):
        playwright_started = asyncio.Event()
        system_started = asyncio.Event()
        release = asyncio.Event()

        async def playwright(_user):
            playwright_started.set()
            await release.wait()
            return "http://playwright"

        async def system(_user):
            system_started.set()
            await release.wait()
            return "http://pc"

        user = {"id": "u", "nombre": "Ruben"}
        with (
            patch.object(antigravity_chat, "asegurar_playwright", side_effect=playwright),
            patch.object(
                antigravity_chat.system_link, "asegurar_sistema", side_effect=system
            ),
            patch.object(antigravity_chat, "escribir_configuracion_mcp"),
            patch.object(
                antigravity_chat.agy_process.AgyProcess,
                "start",
                return_value=_HealthyProcess(),
            ),
        ):
            task = asyncio.create_task(
                antigravity_chat._process_for(user, Path("workspace"))
            )
            await asyncio.wait_for(playwright_started.wait(), 1)
            await asyncio.sleep(0.05)
            both_started = system_started.is_set()
            release.set()
            await asyncio.wait_for(task, 2)

        self.assertTrue(both_started)


class _Pty:
    def __init__(self):
        self.is_alive = True

    def isalive(self):
        return self.is_alive

    def terminate(self, _force):
        self.is_alive = False


class CacheDeSalud(TestCase):
    def setUp(self):
        self.pty = _Pty()
        self.process = agy_process.AgyProcess(self.pty, 4321, Path("agy.log"))

    def test_reutiliza_un_exito_durante_un_segundo(self):
        client = Mock()
        client.conversations.return_value = []
        with (
            patch.object(agy_process.agy_client, "AgyClient", return_value=client),
            patch.object(
                agy_process.time,
                "monotonic",
                side_effect=(100.0, 100.1, 100.5, 101.2, 101.3),
            ),
        ):
            self.assertTrue(self.process.healthy(max_age=1.0))
            self.assertTrue(self.process.healthy(max_age=1.0))
            self.assertTrue(self.process.healthy(max_age=1.0))

        self.assertEqual(client.conversations.call_count, 2)

    def test_un_proceso_muerto_no_usa_el_exito_cacheado(self):
        client = Mock()
        client.conversations.return_value = []
        with (
            patch.object(agy_process.agy_client, "AgyClient", return_value=client),
            patch.object(agy_process.time, "monotonic", side_effect=(100.0, 100.2)),
        ):
            self.assertTrue(self.process.healthy(max_age=1.0))
            self.pty.is_alive = False
            self.assertFalse(self.process.healthy(max_age=1.0))

        self.assertEqual(client.conversations.call_count, 1)

    def test_un_fallo_no_se_cachea(self):
        client = Mock()
        client.conversations.side_effect = (agy_client.AgyError("caído"), [])
        with (
            patch.object(agy_process.agy_client, "AgyClient", return_value=client),
            patch.object(
                agy_process.time, "monotonic", side_effect=(100.0, 100.1, 100.2)
            ),
        ):
            self.assertFalse(self.process.healthy(max_age=1.0))
            self.assertTrue(self.process.healthy(max_age=1.0))

        self.assertEqual(client.conversations.call_count, 2)

    def test_el_cache_empieza_despues_de_una_consulta_lenta(self):
        client = Mock()
        client.conversations.return_value = []
        with (
            patch.object(agy_process.agy_client, "AgyClient", return_value=client),
            patch.object(
                agy_process.time, "monotonic", side_effect=(100.0, 101.5, 102.0)
            ),
        ):
            self.assertTrue(self.process.healthy(max_age=1.0))
            self.assertTrue(self.process.healthy(max_age=1.0))

        self.assertEqual(client.conversations.call_count, 1)


class _ToolStreamClient:
    def stream_updates(self, _cascade_id, skip_text=""):
        def updates():
            yield agy_client.Update(activity=True, tools_running=True)
            time.sleep(0.03)
            yield agy_client.Update(text="Hecho.", done=True)

        return updates()

    def stop(self, _cascade_id):
        return None


class _StreamConColaMuda:
    """Termina de escribir y luego se queda un rato sin cerrar el turno.

    Es el caso que hay que poder distinguir: si el modelo ya dijo lo que tenía
    que decir y lo que falta es el cierre del stream, ese tiempo es espera
    regalada —y en la cara es peor de lo que parece, porque la voz ya terminó
    de locutar mientras el turno sigue ocupado—.
    """

    def stream_updates(self, _cascade_id, skip_text=""):
        def updates():
            time.sleep(0.02)  # lo que el modelo tarda en arrancar
            yield agy_client.Update(text="Ya está", done=False)
            yield agy_client.Update(text="Ya está hecho.", done=True)
            # Sin más texto: solo latidos hasta que el stream se cierra.
            time.sleep(0.08)
            yield agy_client.Update(activity=True)

        return updates()

    def stop(self, _cascade_id):
        return None


class SepararElTextoDelCierre(IsolatedAsyncioTestCase):
    """Sin saber cuándo llegó el último texto no se puede repartir la culpa.

    `post_tool_ms` mezcla dos cosas distintas: el modelo redactando después de
    una herramienta y el turno esperando a que el stream se cierre. La primera
    no se puede acelerar; la segunda es tiempo tirado.
    """

    async def test_apunta_cuando_llego_el_ultimo_texto(self):
        timing = turn_telemetry.TurnTelemetry(route="agy")
        session = antigravity_chat._LiveSession(
            conversation_id="c",
            process=None,
            client=_StreamConColaMuda(),
            cascade_id="cascade-1",
            user_id="u",
        )

        respuesta = await antigravity_chat._consume_turn(
            session, {"id": "u"}, "c", turn_id=None, telemetry=timing
        )
        payload = timing.finish()

        self.assertEqual(respuesta, "Ya está hecho.")
        primero = payload["time_to_first_text_ms"]
        ultimo = payload["time_to_last_text_ms"]
        self.assertGreater(ultimo, 0)
        self.assertGreaterEqual(ultimo, primero)
        # Y el silencio de después queda fuera: es la cola que interesa medir.
        self.assertGreaterEqual(payload["total_ms"] - ultimo, 70)


class EtapasDelStream(IsolatedAsyncioTestCase):
    async def test_mide_primer_texto_y_tiempo_de_herramienta(self):
        timing = turn_telemetry.TurnTelemetry(route="agy")
        session = antigravity_chat._LiveSession(
            conversation_id="c",
            process=None,
            client=_ToolStreamClient(),
            cascade_id="cascade-1",
            user_id="u",
        )

        response = await antigravity_chat._consume_turn(
            session,
            {"id": "u"},
            "c",
            turn_id=None,
            telemetry=timing,
        )
        payload = timing.finish()

        self.assertEqual(response, "Hecho.")
        self.assertGreater(payload["time_to_first_text_ms"], 0)
        self.assertGreaterEqual(payload["tool_running_ms"], 20)
        self.assertGreaterEqual(payload["post_tool_ms"], 0)

if __name__ == "__main__":
    import unittest

    unittest.main()

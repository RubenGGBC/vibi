"""Integración del carril rápido con la conversación persistente."""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from app import db, fast_actions
from app.config import settings
from app.executors import chat, claude_chat
from app.executors.chat_engine import ChatResult


def _execution(status: str, **fields) -> dict:
    return {
        "status": "succeeded",
        "result": {
            "device": {"name": "PC"},
            "state": "ok",
            "message": None,
            "node_dispatch_ms": 8,
            "result": {"status": status, **fields},
        },
    }


class FakeEngine:
    name = "fake"
    display_name = "Fake"

    def __init__(self, *, needs_history=False, response="Respuesta del motor"):
        self.lock = asyncio.Lock()
        self.needs_history = Mock(return_value=needs_history)
        self.run_turn = AsyncMock(return_value=ChatResult(response))
        self.close_session = AsyncMock()
        self.invalidate_session = AsyncMock()
        self.abandon_session = AsyncMock()

    def conversation_lock(self, _conversation_id):
        return self.lock


class CarrilRapidoEnChat(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(asyncio.to_thread, self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.setting_patches = [
            patch.object(settings, "db_path", str(root / "morgana.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
        ]
        for setting_patch in self.setting_patches:
            setting_patch.start()
            self.addCleanup(setting_patch.stop)
        db.init_db()
        self.user = db.get_or_create_user("ruben")
        self.engine = FakeEngine()
        self.engine_patch = patch.object(chat, "engine_for", return_value=self.engine)
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)
        self.event_patches = {
            name: patch.object(chat.events, name, AsyncMock())
            for name in (
                "mensaje_chat",
                "inicio_respuesta_chat",
                "fin_respuesta_chat",
            )
        }
        for event_patch in self.event_patches.values():
            event_patch.start()
            self.addCleanup(event_patch.stop)

    async def test_exito_persiste_eventos_y_no_llama_al_motor(self):
        execution = _execution(
            "launched",
            app={"id": "app_1", "label": "Spotify"},
            node_execution_ms=4,
        )
        self.engine.needs_history.side_effect = AssertionError(
            "El carril rápido no debe construir historial"
        )
        with patch.object(
            fast_actions.tools, "execute", AsyncMock(return_value=execution)
        ):
            result = await chat.respond(self.user, "Abre Spotify", "pwa")

        self.assertEqual(result, ChatResult("Abriendo Spotify."))
        self.engine.run_turn.assert_not_awaited()
        self.engine.invalidate_session.assert_awaited_once_with(
            self.user, db.get_active_conversation(self.user["id"])["id"]
        )
        conversation = db.get_active_conversation(self.user["id"])
        messages = db.list_context_messages(conversation["id"], 12_000)
        self.assertEqual(
            [(message["role"], message["content"]) for message in messages],
            [("user", "Abre Spotify"), ("assistant", "Abriendo Spotify.")],
        )
        self.assertEqual(chat.events.mensaje_chat.await_count, 2)
        chat.events.inicio_respuesta_chat.assert_awaited_once()
        chat.events.fin_respuesta_chat.assert_awaited_once()
        timing_events, _ = db.list_events_for_user(
            self.user["id"], event_types=("turno_accion_rapida",)
        )
        self.assertEqual(len(timing_events), 1)
        payload = json.loads(timing_events[0]["payload"])
        self.assertEqual(payload["route"], "fast_action")
        self.assertEqual(payload["status"], "launched")
        self.assertEqual(payload["node_dispatch_ms"], 8)
        self.assertEqual(payload["node_execution_ms"], 4)
        self.assertNotIn("Spotify", repr(payload))

    async def test_not_found_llega_una_sola_vez_al_motor(self):
        with patch.object(
            fast_actions.tools,
            "execute",
            AsyncMock(return_value=_execution("not_found", candidates=[])),
        ):
            result = await chat.respond(self.user, "Abre Desconocida", "pwa")

        self.assertEqual(result.response, "Respuesta del motor")
        self.engine.run_turn.assert_awaited_once()
        self.assertEqual(self.engine.run_turn.await_args.args[2], "Abre Desconocida")
        self.engine.invalidate_session.assert_not_awaited()

    async def test_peticion_compuesta_llega_intacta_al_motor(self):
        with patch.object(fast_actions.tools, "execute", AsyncMock()) as execute:
            await chat.respond(
                self.user,
                "Abre Spotify y pon mi lista de trabajo",
                "pwa",
            )

        execute.assert_not_awaited()
        self.assertEqual(
            self.engine.run_turn.await_args.args[2],
            "Abre Spotify y pon mi lista de trabajo",
        )

    async def test_ambiguedad_y_timeout_no_invocan_ni_reintentan_modelo(self):
        ambiguous = _execution(
            "ambiguous",
            candidates=[
                {"id": "1", "label": "Spotify"},
                {"id": "2", "label": "Spotify Music"},
            ],
        )
        with patch.object(
            fast_actions.tools, "execute", AsyncMock(return_value=ambiguous)
        ):
            first = await chat.respond(self.user, "Abre Spotify", "pwa")
        self.assertIn("¿Cuál quieres?", first.response)

        timeout = _execution("ignored")
        timeout["result"]["state"] = "timeout"
        timeout["result"]["result"] = None
        with patch.object(
            fast_actions.tools, "execute", AsyncMock(return_value=timeout)
        ):
            second = await chat.respond(self.user, "Inicia Calculadora", "pwa")

        self.assertIn("no he podido confirmar", second.response)
        self.engine.run_turn.assert_not_awaited()
        self.assertEqual(self.engine.invalidate_session.await_count, 2)

    async def test_tool_adjunta_desactiva_el_carril(self):
        with patch.object(fast_actions.tools, "execute", AsyncMock()) as execute:
            await chat.respond(
                self.user,
                "Abre Spotify",
                "pwa",
                attached_tool_ids=("files.read",),
            )

        execute.assert_not_awaited()
        self.assertEqual(self.engine.run_turn.await_args.args[3], ("files.read",))

    async def test_turno_siguiente_recibe_la_accion_rapida_en_el_historial(self):
        execution = _execution(
            "launched",
            app={"id": "app_1", "label": "Spotify"},
            node_execution_ms=4,
        )
        with patch.object(
            fast_actions.tools, "execute", AsyncMock(return_value=execution)
        ):
            await chat.respond(self.user, "Abre Spotify", "pwa")

        self.engine.needs_history.return_value = True
        await chat.respond(self.user, "Ahora ciérrala", "pwa")

        history = self.engine.run_turn.await_args.args[5]
        self.assertEqual(
            [(message["role"], message["content"]) for message in history],
            [("user", "Abre Spotify"), ("assistant", "Abriendo Spotify.")],
        )

    async def test_claude_invalida_dentro_del_candado_sin_bloquearse(self):
        conversation = db.get_or_create_active_conversation(self.user["id"])
        db.update_conversation_session(
            conversation["id"], self.user["id"], "sesion-nativa-vieja"
        )
        execution = _execution(
            "launched",
            app={"id": "app_1", "label": "Spotify"},
            node_execution_ms=4,
        )
        with patch.object(chat, "engine_for", return_value=claude_chat.ENGINE), patch.object(
            fast_actions.tools, "execute", AsyncMock(return_value=execution)
        ):
            result = await asyncio.wait_for(
                chat.respond(self.user, "Abre Spotify", "pwa"), timeout=0.5
            )

        self.assertEqual(result.response, "Abriendo Spotify.")
        updated = db.get_active_conversation(self.user["id"])
        self.assertIsNone(updated["claude_session_id"])

    async def test_usa_la_telemetria_completa_que_devuelve_agy(self):
        self.engine.name = "antigravity"
        payload = {
            "route": "agy",
            "route_decision_ms": 99_999,
            "session_health_ms": 2,
            "stream_open_ms": 3,
            "input_ack_ms": 4,
            "time_to_first_text_ms": 5,
            "tool_running_ms": 6,
            "node_dispatch_ms": 0,
            "node_execution_ms": 0,
            "post_tool_ms": 7,
            "total_ms": 99_999,
        }
        self.engine.run_turn.return_value = ChatResult(
            "Respuesta del motor", telemetry=payload
        )

        with patch.object(chat, "log") as log:
            result = await chat.respond(self.user, "Cuéntame algo", "pwa")

        log.info.assert_called_once()
        _, final_payload = log.info.call_args.args
        self.assertEqual(final_payload["route"], "agy")
        self.assertEqual(final_payload["session_health_ms"], 2)
        self.assertEqual(final_payload["tool_running_ms"], 6)
        self.assertNotEqual(final_payload["route_decision_ms"], 99_999)
        self.assertNotEqual(final_payload["total_ms"], 99_999)
        self.assertEqual(result.telemetry, final_payload)

    async def test_caida_de_agy_clasifica_y_devuelve_el_payload_como_fallback(self):
        self.engine.name = "antigravity"
        self.engine.display_name = "Antigravity"
        self.engine.run_turn.side_effect = RuntimeError("agy no responde")
        respaldo = FakeEngine(response="Respuesta de Claude")

        with (
            patch.object(
                chat,
                "_engines",
                return_value={"anthropic": respaldo, "antigravity": self.engine},
            ),
            patch.object(chat, "precalentar_en_segundo_plano"),
            patch.object(chat, "log") as log,
        ):
            result = await chat.respond(self.user, "Cuéntame algo", "pwa")

        _, final_payload = log.info.call_args.args
        self.assertEqual(final_payload["route"], "fallback")
        self.assertEqual(result.telemetry, final_payload)
        self.assertIn("Respuesta de Claude", result.response)


if __name__ == "__main__":
    import unittest

    unittest.main()

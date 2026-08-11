from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from app.channels import telegram
from app.config import settings


class TelegramNotificationTests(IsolatedAsyncioTestCase):
    async def test_notificacion_de_tarea_incluye_deep_link_y_acciones(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        app = SimpleNamespace(bot=bot)
        user = {"id": "u1", "telegram_chat_id": 42}
        with patch.object(telegram.db, "get_user_by_id", return_value=user), patch.object(
            telegram, "_app", app
        ), patch.object(settings, "pwa_base_url", "https://vibi.example/"):
            await telegram.notificar("u1", "Plan listo", "t1", acciones=True)

        sent = bot.send_message.await_args.kwargs
        self.assertEqual(
            sent["text"],
            "Plan listo\n\n🔗 https://vibi.example/tareas/t1",
        )
        self.assertIsNotNone(sent["reply_markup"])

    async def test_notificacion_final_tiene_link_pero_no_botones(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        app = SimpleNamespace(bot=bot)
        user = {"id": "u1", "telegram_chat_id": 42}
        with patch.object(telegram.db, "get_user_by_id", return_value=user), patch.object(
            telegram, "_app", app
        ), patch.object(settings, "pwa_base_url", "https://vibi.example"):
            await telegram.notificar("u1", "Completada", "t1", acciones=False)

        sent = bot.send_message.await_args.kwargs
        self.assertIn("https://vibi.example/tareas/t1", sent["text"])
        self.assertIsNone(sent["reply_markup"])


class TelegramButtonTests(IsolatedAsyncioTestCase):
    def _update(self, data: str):
        query = SimpleNamespace(
            data=data,
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        return SimpleNamespace(
            effective_chat=SimpleNamespace(id=42), callback_query=query
        )

    async def test_no_permite_actuar_sobre_tarea_ajena(self):
        update = self._update("aprobar:t2")
        with patch.object(
            telegram.db, "user_by_chat_id", return_value={"id": "u1"}
        ), patch.object(
            telegram.db,
            "get_task",
            return_value={"id": "t2", "user_id": "u2"},
        ), patch.object(
            telegram.tasks, "aprobar_tarea", AsyncMock()
        ) as approve:
            await telegram.botones(update, SimpleNamespace())

        approve.assert_not_awaited()
        update.callback_query.answer.assert_awaited_once_with(
            "Esta tarea no te pertenece.", show_alert=True
        )

    async def test_aprobacion_valida_conserva_boton_y_mensaje(self):
        update = self._update("aprobar:t1")
        with patch.object(
            telegram.db, "user_by_chat_id", return_value={"id": "u1"}
        ), patch.object(
            telegram.db,
            "get_task",
            return_value={"id": "t1", "user_id": "u1"},
        ), patch.object(
            telegram.tasks, "aprobar_tarea", AsyncMock(return_value=True)
        ):
            await telegram.botones(update, SimpleNamespace())

        update.callback_query.edit_message_reply_markup.assert_awaited_once_with(None)
        update.callback_query.message.reply_text.assert_awaited_once()

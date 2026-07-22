from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from app.channels import telegram
from app.core.messages import ResultadoMensaje


class TelegramSharedCoreTests(IsolatedAsyncioTestCase):
    async def test_mensaje_delega_en_el_core_compartido(self):
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=42),
            message=SimpleNamespace(text="hola", reply_text=reply_text),
        )
        context = SimpleNamespace(user_data={})
        user = {"id": "u1", "nombre": "Rubén"}

        with patch.object(telegram.db, "user_by_chat_id", return_value=user), patch(
            "app.channels.telegram.message_core.procesar_mensaje",
            AsyncMock(return_value=ResultadoMensaje("rapida", respuesta="respuesta")),
        ) as procesar:
            await telegram.mensaje(update, context)

        procesar.assert_awaited_once_with(user, "hola", canal="telegram")
        reply_text.assert_awaited_once_with("respuesta")

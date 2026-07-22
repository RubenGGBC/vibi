from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.config import settings
from app.executors import groq_chat
from tests.test_groq_chat import FakeGroqClient


class GroqCompoundRoleTests(IsolatedAsyncioTestCase):
    def setUp(self):
        groq_chat._historiales.clear()
        self.fake = FakeGroqClient([RuntimeError("Compound no disponible"), "fallback"])
        self.client_patch = patch.object(groq_chat, "_client", self.fake)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    async def test_usa_developer_en_compound_y_system_en_fallback(self):
        with patch.object(settings, "groq_web_search_enabled", True), \
             patch.object(settings, "groq_search_model", "groq/compound"), \
             patch.object(settings, "groq_model", "llama-normal"):
            await groq_chat.responder("u1", "Rubén", "Busca información actual")

        llamadas = self.fake.chat.completions.calls
        self.assertEqual(llamadas[0]["messages"][0]["role"], "developer")
        self.assertEqual(llamadas[1]["messages"][0]["role"], "system")

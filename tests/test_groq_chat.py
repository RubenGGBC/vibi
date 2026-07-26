import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app import db
from app.config import settings
from app.executors import groq_chat


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=response),
                )
            ]
        )


class FakeGroqClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(responses),
        )


class GroqChatTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_patch = patch.object(
            settings, "db_path", str(Path(self.tempdir.name) / "morgana.db")
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        db.init_db()
        self.user = db.get_or_create_user("Rubén")
        self.fake = FakeGroqClient(["respuesta actual"])
        self.client_patch = patch.object(groq_chat, "_client", self.fake)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    async def test_usa_compound_cuando_la_busqueda_esta_habilitada(self):
        with patch.object(settings, "groq_web_search_enabled", True), \
             patch.object(settings, "groq_search_model", "groq/compound"), \
             patch.object(settings, "groq_model", "llama-normal"):
            resultado = await groq_chat.responder(
                self.user["id"], "Rubén", "¿Qué ha pasado hoy?"
            )

        self.assertEqual(resultado, "respuesta actual")
        self.assertEqual(
            self.fake.chat.completions.calls[0]["model"],
            "groq/compound",
        )

    async def test_usa_modelo_normal_cuando_la_busqueda_esta_deshabilitada(self):
        with patch.object(settings, "groq_web_search_enabled", False), \
             patch.object(settings, "groq_model", "llama-normal"):
            await groq_chat.responder(self.user["id"], "Rubén", "Hola")

        self.assertEqual(
            self.fake.chat.completions.calls[0]["model"],
            "llama-normal",
        )

    async def test_conserva_el_historial_entre_respuestas(self):
        self.fake.chat.completions.responses = ["primera", "segunda"]
        with patch.object(settings, "groq_web_search_enabled", False):
            await groq_chat.responder(self.user["id"], "Rubén", "primera pregunta")
            await groq_chat.responder(self.user["id"], "Rubén", "segunda pregunta")

        mensajes = self.fake.chat.completions.calls[1]["messages"]
        self.assertEqual(
            [(m["role"], m["content"]) for m in mensajes[-3:]],
            [
                ("user", "primera pregunta"),
                ("assistant", "primera"),
                ("user", "segunda pregunta"),
            ],
        )

    async def test_reintenta_con_modelo_normal_si_compound_falla(self):
        self.fake.chat.completions.responses = [
            RuntimeError("Compound no disponible"),
            "respuesta fallback",
        ]
        with patch.object(settings, "groq_web_search_enabled", True), \
             patch.object(settings, "groq_search_model", "groq/compound"), \
             patch.object(settings, "groq_model", "llama-normal"):
            resultado = await groq_chat.responder(
                self.user["id"], "Rubén", "Busca el dato actual"
            )

        self.assertEqual(resultado, "respuesta fallback")
        self.assertEqual(
            [call["model"] for call in self.fake.chat.completions.calls],
            ["groq/compound", "llama-normal"],
        )

    async def test_documento_usa_modelo_normal_y_se_incluye_como_dato(self):
        with patch.object(settings, "groq_web_search_enabled", True), \
             patch.object(settings, "groq_model", "llama-normal"):
            await groq_chat.responder(
                self.user["id"],
                "Rubén",
                "¿Qué pone?",
                document_context=("matricula.pdf", "Cuarto de Informática"),
            )

        call = self.fake.chat.completions.calls[0]
        self.assertEqual(call["model"], "llama-normal")
        self.assertEqual(call["messages"][0]["role"], "system")
        self.assertIn("matricula.pdf", call["messages"][0]["content"])
        self.assertIn("Cuarto de Informática", call["messages"][0]["content"])

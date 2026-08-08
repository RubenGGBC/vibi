import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from app import ai_providers, db
from app.config import settings
from app.executors import claude_agent


class AIProviderSettingsTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.patches = [
            patch.object(
                settings,
                "db_path",
                str(Path(self.tempdir.name) / "morgana.db"),
            ),
            patch.object(
                settings,
                "credential_encryption_key",
                "clave-de-cifrado-para-pruebas-con-32-bytes",
            ),
            patch.object(settings, "anthropic_api_key", ""),
            patch.object(settings, "groq_api_key", ""),
        ]
        for setting_patch in self.patches:
            setting_patch.start()
            self.addCleanup(setting_patch.stop)
        db.init_db()
        self.user = db.get_or_create_user("ana")

    def test_haiku_es_el_orquestador_predeterminado(self):
        configured = ai_providers.get_settings(self.user["id"])

        self.assertEqual(configured.tools_provider, "anthropic")
        self.assertEqual(configured.tools_model, "claude-haiku-4-5")

    def test_cifra_clave_personal_y_no_la_expone(self):
        secret = "sk-ant-clave-personal-super-secreta"
        ai_providers.set_api_key(self.user["id"], "anthropic", secret)

        encrypted = db.get_provider_credential(self.user["id"], "anthropic")
        public = ai_providers.public_settings(self.user["id"])

        self.assertNotIn(secret, encrypted)
        self.assertEqual(
            ai_providers.get_api_key(self.user["id"], "anthropic"), secret
        )
        self.assertEqual(
            public["credentials"]["anthropic"],
            {"configured": True, "source": "personal"},
        )
        self.assertNotIn(secret, repr(public))

    def test_hace_fallback_a_groq_si_anthropic_no_tiene_clave(self):
        ai_providers.set_api_key(
            self.user["id"], "groq", "gsk_clave_personal_de_pruebas"
        )

        resolved = ai_providers.resolve_lane(self.user["id"], "tools")

        self.assertEqual(resolved.provider, "groq")
        self.assertEqual(resolved.model, settings.groq_model)
        self.assertTrue(resolved.fallback)


class AIProviderCompletionTests(IsolatedAsyncioTestCase):
    async def test_tools_usa_el_modelo_anthropic_configurado(self):
        response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"via":"rapida"}')]
        )
        messages = SimpleNamespace(create=AsyncMock(return_value=response))
        client = SimpleNamespace(messages=messages)
        resolved = ai_providers.ResolvedLane(
            "anthropic", "claude-haiku-4-5", "sk-ant-test"
        )
        with patch(
            "app.ai_providers.resolve_lane", return_value=resolved
        ), patch("app.ai_providers.AsyncAnthropic", return_value=client):
            text = await ai_providers.complete_text(
                "u1",
                "tools",
                [
                    {"role": "system", "content": "Clasifica"},
                    {"role": "user", "content": "Busca mi archivo"},
                ],
                max_tokens=180,
                json_mode=True,
            )

        self.assertEqual(text, '{"via":"rapida"}')
        self.assertEqual(messages.create.await_args.kwargs["model"], "claude-haiku-4-5")
        self.assertEqual(messages.create.await_args.kwargs["system"], "Clasifica")

    async def test_modo_suscripcion_ignora_la_clave_personal(self):
        # En subscription manda el login OAuth de la cuenta Pro/Max. Cualquier
        # key heredada o guardada en la configuración tiene prioridad para el
        # CLI y le hace descartar el OAuth, así que hay que vaciarla.
        with patch.object(settings, "claude_auth_mode", "subscription"), patch(
            "app.executors.claude_agent.ai_providers.get_personal_api_key",
            return_value="sk-ant-personal",
        ), patch(
            "app.executors.claude_agent.ai_providers.get_api_key",
            return_value="sk-ant-personal",
        ):
            options = claude_agent._opciones_comunes(
                "u1", "Ana", "C:/workspace/demo", "claude-haiku-4-5"
            )

        self.assertEqual(options["env"], {"ANTHROPIC_API_KEY": ""})

    async def test_clave_personal_prevalece_en_modo_auto(self):
        with patch.object(settings, "claude_auth_mode", "auto"), patch(
            "app.executors.claude_agent.ai_providers.get_personal_api_key",
            return_value="sk-ant-personal",
        ), patch(
            "app.executors.claude_agent.ai_providers.get_api_key",
            return_value="sk-ant-personal",
        ):
            options = claude_agent._opciones_comunes(
                "u1", "Ana", "C:/workspace/demo", "claude-haiku-4-5"
            )

        self.assertEqual(options["env"], {"ANTHROPIC_API_KEY": "sk-ant-personal"})

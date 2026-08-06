"""El canal de voz habla distinto y busca menos que el canal de texto."""
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from app.core import messages
from app.executors import claude_chat


class PromptDeLocucionTests(TestCase):
    def test_el_canal_de_texto_no_recibe_instrucciones_de_locucion(self):
        prompt = claude_chat._prompt_with_attachments("¿Qué tiempo hace?", (), {})

        self.assertNotIn("<locucion>", prompt)
        self.assertNotIn("<busqueda_breve>", prompt)

    def test_el_canal_de_voz_pide_redactar_para_el_oido(self):
        prompt = claude_chat._prompt_with_attachments(
            "¿Qué tiempo hace?", (), {}, voz=True
        )

        self.assertIn("<locucion>", prompt)
        # Lo esencial: nada de markdown y cifras habladas.
        self.assertIn("markdown", prompt.lower())
        self.assertIn("veinticuatro grados", prompt)

    def test_el_canal_de_voz_prohibe_locutar_las_fuentes(self):
        prompt = claude_chat._prompt_with_attachments(
            "¿Qué han dicho hoy del Athletic?", (), {}, voz=True
        )

        # Compound y la búsqueda web cierran con un listado que suena fatal.
        self.assertIn("PROHIBIDO el apartado de fuentes", prompt)
        self.assertIn("Referencias", prompt)

    def test_el_canal_de_voz_traduce_la_barra_a_palabras(self):
        prompt = claude_chat._prompt_with_attachments(
            "¿Qué nota tiene esa película?", (), {}, voz=True
        )

        # «5/5» se locutaba como «cinco barra cinco».
        self.assertIn("cinco sobre cinco", prompt)
        self.assertIn("nunca se dice «barra»", prompt)

    def test_el_canal_de_voz_acota_las_busquedas_en_internet(self):
        prompt = claude_chat._prompt_with_attachments(
            "¿Qué tiempo hará mañana en Bilbao?", (), {}, voz=True
        )

        self.assertIn("<busqueda_breve>", prompt)
        self.assertIn("UNA sola búsqueda", prompt)

    def test_la_locucion_convive_con_el_historial_y_las_tools(self):
        prompt = claude_chat._prompt_with_attachments(
            "Sigue",
            ("files.search",),
            {"files.search": ("files_search", "Buscar archivos")},
            bootstrap_history=({"role": "user", "content": "Hola"},),
            voz=True,
        )

        self.assertIn("<historial_previo>", prompt)
        self.assertIn("<herramientas_adjuntas>", prompt)
        self.assertIn("<locucion>", prompt)


class EsfuerzoDeSesionTests(TestCase):
    def test_la_conversacion_usa_effort_bajo_para_responder_antes(self):
        # Medido: sin effort los turnos oscilan 1,2-3,0 s y la caché se rompe;
        # con effort bajo se quedan en ~1,2 s y cache_creation cae a cero.
        self.assertEqual(claude_chat.CHAT_EFFORT, "low")


class SesionHuerfanaTests(IsolatedAsyncioTestCase):
    """Si el transcript de Claude Code desapareció, no se rompe la conversación."""

    async def test_reintenta_sin_resume_y_olvida_la_sesion_perdida(self):
        conversation = {"id": "c1", "claude_session_id": "fantasma"}
        user = {"id": "u1", "nombre": "Rubén", "is_admin": False}
        intentos: list[str | None] = []

        class FakeClient:
            def __init__(self, options):
                self.options = options

            async def connect(self):
                intentos.append(self.options.resume)
                if self.options.resume:
                    raise RuntimeError(
                        "No conversation found with session ID: fantasma"
                    )

        with patch.object(claude_chat, "ClaudeSDKClient", FakeClient), patch.object(
            claude_chat, "_build_mcp_tools", return_value=([], {})
        ), patch.object(
            claude_chat, "create_sdk_mcp_server", return_value=object()
        ), patch.object(
            claude_chat.tasks, "directorio_usuario", return_value="/w"
        ), patch.object(
            claude_chat, "_opciones_comunes", return_value={"model": "m"}
        ), patch.object(
            claude_chat.db, "update_conversation_session"
        ) as olvidar:
            session = await claude_chat._create_live_session(
                user, conversation, [], "firma"
            )

        # Primero con la sesión guardada; al fallar, otra vez desde cero.
        self.assertEqual(intentos, ["fantasma", None])
        olvidar.assert_called_once_with("c1", "u1", None)
        self.assertIsNone(session.session_id)
        # Sin transcript que reanudar hay que reinyectar el historial.
        self.assertTrue(session.needs_history)

    async def test_un_fallo_sin_resume_se_propaga(self):
        class FakeClient:
            def __init__(self, options):
                self.options = options

            async def connect(self):
                raise RuntimeError("claude no está instalado")

        with patch.object(claude_chat, "ClaudeSDKClient", FakeClient), patch.object(
            claude_chat, "_build_mcp_tools", return_value=([], {})
        ), patch.object(
            claude_chat, "create_sdk_mcp_server", return_value=object()
        ), patch.object(
            claude_chat.tasks, "directorio_usuario", return_value="/w"
        ), patch.object(
            claude_chat, "_opciones_comunes", return_value={"model": "m"}
        ):
            with self.assertRaises(RuntimeError):
                await claude_chat._create_live_session(
                    {"id": "u1", "nombre": "Rubén"},
                    {"id": "c1", "claude_session_id": None},
                    [],
                    "firma",
                )


class CanalDeVozTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = {"id": "u1", "nombre": "Rubén"}
        for target in (
            "app.core.messages.db.log_event",
            "app.core.messages.skills.parse_command",
        ):
            patcher = patch(target, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _procesar(self, canal: str):
        with patch(
            "app.core.messages.chat.respond",
            AsyncMock(return_value=claude_chat.ChatResult(response="Hace sol.")),
        ) as respond:
            await messages.procesar_mensaje(self.user, "¿Qué tiempo hace?", canal=canal)
        return respond

    async def test_el_canal_cara_marca_el_turno_como_voz(self):
        respond = await self._procesar("cara")

        self.assertTrue(respond.await_args.kwargs["voz"])

    async def test_el_canal_pwa_no_marca_el_turno_como_voz(self):
        respond = await self._procesar("pwa")

        self.assertFalse(respond.await_args.kwargs["voz"])

"""`/model` en el hilo de chat: elegir y cambiar el modelo de agy y su effort.

Sigue el mismo camino que `/skill` en `procesar_mensaje` —se intercepta antes
de llegar al motor de chat, queda escrito en la conversación como cualquier
otro turno, y fuerza que la sesión se reconstruya—, así que las pruebas
comparten el montaje de base de datos real de `test_skills.py` en vez de un
doble: lo que se prueba es que el turno queda persistido, no una llamada
simulada.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from app import ai_providers, db
from app.config import settings
from app.core import messages
from app.executors import agy_modelos


def _modelo(id_="gemini-3.8-flash-high", etiqueta="Gemini 3.8 Flash (High)"):
    return agy_modelos.Modelo(id=id_, etiqueta=etiqueta)


LISTA = [
    _modelo(),
    agy_modelos.Modelo(id="claude-sonnet-4-6", etiqueta="Claude Sonnet 4.6 (Thinking)"),
]


class ComandoModelEnElHilo(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_patch = patch.object(
            settings, "db_path", str(Path(self.tempdir.name) / "vibi.db")
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        db.init_db()
        self.user = db.get_or_create_user("ana")

    async def test_fijar_un_modelo_conocido_se_guarda_y_no_va_al_chat(self):
        with patch(
            "app.core.messages.agy_modelos.listar", return_value=LISTA
        ), patch(
            "app.core.messages.antigravity_chat.aplicar_perfil", AsyncMock()
        ) as aplicar, patch(
            "app.core.messages.chat.respond",
            AsyncMock(side_effect=AssertionError("el comando no debe ir al chat")),
        ) as respond:
            result = await messages.procesar_mensaje(
                self.user, "/model gemini-3.8-flash-high", canal="pwa"
            )

        respond.assert_not_awaited()
        aplicar.assert_awaited_once_with(self.user)
        self.assertEqual(result.via, "herramienta")
        self.assertIn("Gemini 3.8 Flash (High)", result.respuesta)
        self.assertEqual(
            ai_providers.get_settings(self.user["id"]).chat_model,
            "gemini-3.8-flash-high",
        )
        self.assertEqual(
            ai_providers.get_settings(self.user["id"]).chat_provider, "antigravity"
        )

    async def test_el_turno_queda_escrito_en_la_conversacion(self):
        with patch("app.core.messages.agy_modelos.listar", return_value=LISTA), patch(
            "app.core.messages.antigravity_chat.aplicar_perfil", AsyncMock()
        ):
            await messages.procesar_mensaje(
                self.user, "/model gemini-3.8-flash-high", canal="pwa"
            )

        stored = db.list_active_conversation_messages(self.user["id"], 10)
        self.assertEqual(stored[0]["content"], "/model gemini-3.8-flash-high")
        self.assertIn("Gemini 3.8 Flash (High)", stored[1]["content"])

    async def test_un_id_desconocido_no_se_guarda_y_lo_dice(self):
        antes = ai_providers.get_settings(self.user["id"])
        with patch("app.core.messages.agy_modelos.listar", return_value=LISTA), patch(
            "app.core.messages.antigravity_chat.aplicar_perfil", AsyncMock()
        ) as aplicar:
            result = await messages.procesar_mensaje(
                self.user, "/model gemini-inventado", canal="pwa"
            )

        aplicar.assert_not_awaited()
        self.assertIn("gemini-inventado", result.respuesta)
        self.assertEqual(ai_providers.get_settings(self.user["id"]), antes)

    async def test_model_a_secas_lista_los_modelos_sin_guardar_nada(self):
        with patch("app.core.messages.agy_modelos.listar", return_value=LISTA), patch(
            "app.core.messages.antigravity_chat.aplicar_perfil", AsyncMock()
        ) as aplicar:
            result = await messages.procesar_mensaje(
                self.user, "/model", canal="pwa"
            )

        aplicar.assert_not_awaited()
        self.assertIn("gemini-3.8-flash-high", result.respuesta)
        self.assertIn("claude-sonnet-4-6", result.respuesta)

    async def test_default_borra_la_eleccion_previa(self):
        with patch("app.core.messages.agy_modelos.listar", return_value=LISTA), patch(
            "app.core.messages.antigravity_chat.aplicar_perfil", AsyncMock()
        ):
            await messages.procesar_mensaje(
                self.user, "/model gemini-3.8-flash-high", canal="pwa"
            )
            await messages.procesar_mensaje(self.user, "/model default", canal="pwa")

        self.assertEqual(ai_providers.get_settings(self.user["id"]).chat_model, "")

    async def test_si_agy_no_contesta_la_lista_el_error_llega_al_hilo(self):
        """`agy models` es una llamada de red real y puede fallar: el usuario
        tiene que verlo en la conversación, no un 500 sin explicación."""
        with patch(
            "app.core.messages.agy_modelos.listar",
            side_effect=agy_modelos.ErrorModelos("agy no contesta"),
        ), patch("app.core.messages.antigravity_chat.aplicar_perfil", AsyncMock()):
            result = await messages.procesar_mensaje(
                self.user, "/model gemini-3.8-flash-high", canal="pwa"
            )

        self.assertIn("agy no contesta", result.respuesta)

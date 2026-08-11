"""Reconocimiento estricto y ejecución del carril rápido."""
from __future__ import annotations

from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from app import fast_actions, tools


class ReconocerApertura(TestCase):
    def test_corpus_aceptado(self):
        cases = {
            "Abre Spotify": "Spotify",
            "inicia Visual Studio Code, por favor": "Visual Studio Code",
            "LANZA la Calculadora.": "Calculadora",
            "ejecuta El Bloc de notas": "Bloc de notas",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                action = fast_actions.recognize_launch(text)
                self.assertIsNotNone(action)
                self.assertEqual(action.app, expected)

    def test_corpus_rechazado(self):
        cases = (
            "No abras Spotify",
            "Abre Spotify y pon mi lista",
            "Abre Spotify, después abre Chrome",
            "Cuando puedas abre Spotify",
            "Abre https://spotify.com",
            r"Abre C:\\Windows\\calc.exe",
            "Abre informe.pdf",
            "Abre Spotify --private-session",
            "Abre Spotify & calc.exe",
            "Abre Spotify y",
            "Abre",
            "¿Puedes abrir Spotify?",
            "Cierra Spotify",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(fast_actions.recognize_launch(text))

    def test_tools_adjuntas_desactivan_el_carril(self):
        self.assertIsNone(
            fast_actions.recognize_launch(
                "Abre Spotify", attached_tool_ids=("devices.launch_app",)
            )
        )


def _execution(status: str, **result_fields) -> dict:
    result = {"status": status, **result_fields}
    return {
        "status": "succeeded",
        "result": {
            "device": {"name": "PC"},
            "state": "ok",
            "message": None,
            "result": result,
            "node_dispatch_ms": 12,
        },
    }


class EjecutarAccion(IsolatedAsyncioTestCase):
    async def test_exito_se_redacta_sin_modelo_y_copia_tiempos(self):
        action = fast_actions.LaunchAction("Spotify")
        execution = _execution(
            "launched",
            app={"id": "app_1", "label": "Spotify"},
            node_execution_ms=5,
        )
        with patch.object(tools, "execute", AsyncMock(return_value=execution)) as execute:
            outcome = await fast_actions.execute_fast_action({"id": "u"}, action)

        execute.assert_awaited_once_with(
            "devices.launch_app", {"id": "u"}, {"app": "Spotify"}
        )
        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.response, "Abriendo Spotify.")
        self.assertEqual(outcome.status, "launched")
        self.assertEqual(outcome.node_dispatch_ms, 12)
        self.assertEqual(outcome.node_execution_ms, 5)

    async def test_ambiguedad_pregunta_con_lista_acotada(self):
        execution = _execution(
            "ambiguous",
            candidates=[
                {"id": "1", "label": "Spotify"},
                {"id": "2", "label": "Spotify Music"},
            ],
        )
        with patch.object(tools, "execute", AsyncMock(return_value=execution)):
            outcome = await fast_actions.execute_fast_action(
                {"id": "u"}, fast_actions.LaunchAction("Spotify")
            )

        self.assertTrue(outcome.handled)
        self.assertEqual(
            outcome.response,
            "He encontrado Spotify y Spotify Music. ¿Cuál quieres?",
        )

    async def test_not_found_y_catalogo_frio_caen_al_motor(self):
        for status in ("not_found", "catalog_starting"):
            with self.subTest(status=status):
                with patch.object(
                    tools, "execute", AsyncMock(return_value=_execution(status))
                ):
                    outcome = await fast_actions.execute_fast_action(
                        {"id": "u"}, fast_actions.LaunchAction("Desconocida")
                    )
                self.assertFalse(outcome.handled)
                self.assertEqual(outcome.status, status)

    async def test_fallo_posterior_no_se_reintenta_con_modelo(self):
        execution = _execution(
            "launch_failed",
            app={"id": "app_1", "label": "Spotify"},
            error="Windows la rechazó",
        )
        with patch.object(tools, "execute", AsyncMock(return_value=execution)):
            outcome = await fast_actions.execute_fast_action(
                {"id": "u"}, fast_actions.LaunchAction("Spotify")
            )

        self.assertTrue(outcome.handled)
        self.assertEqual(
            outcome.response, "Encontré Spotify, pero Windows no pudo abrirlo."
        )

    async def test_timeout_de_entrega_es_terminal_para_no_duplicar(self):
        execution = _execution("ignored")
        execution["result"]["state"] = "timeout"
        execution["result"]["result"] = None
        with patch.object(tools, "execute", AsyncMock(return_value=execution)):
            outcome = await fast_actions.execute_fast_action(
                {"id": "u"}, fast_actions.LaunchAction("Spotify")
            )

        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.status, "timeout")
        self.assertEqual(
            outcome.response,
            "He enviado la orden, pero no he podido confirmar si se abrió.",
        )

    async def test_nodo_offline_deja_la_peticion_completa_al_motor(self):
        with patch.object(
            tools,
            "execute",
            AsyncMock(side_effect=tools.ToolError("PC no está conectado")),
        ):
            outcome = await fast_actions.execute_fast_action(
                {"id": "u"}, fast_actions.LaunchAction("Spotify")
            )

        self.assertFalse(outcome.handled)
        self.assertEqual(outcome.status, "fallback")


if __name__ == "__main__":
    import unittest

    unittest.main()

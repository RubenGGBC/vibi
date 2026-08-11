"""Contrato de la capacidad tipada para abrir aplicaciones."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from morgana_node import app_catalog, capabilities  # noqa: E402
from morgana_node.config import NodeConfig  # noqa: E402

from app import db, nodes, tools
from app.config import settings


class CapacidadDelAgente(TestCase):
    def setUp(self):
        self.config = NodeConfig(
            url="https://morgana.local",
            node_id="node-1",
            token="token",
            nombre="PC",
            projects_root=".",
        )

    def test_el_agente_delega_solo_el_alias_en_el_catalogo(self):
        with patch.object(
            app_catalog.catalog,
            "launch",
            return_value={"status": "launched", "app": {"label": "Spotify"}},
        ) as launch:
            result = capabilities.run(self.config, "apps.launch", {"app": "Spotify"})

        self.assertEqual(result["status"], "launched")
        launch.assert_called_once_with("Spotify")

    def test_el_agente_rechaza_un_alias_vacio(self):
        with self.assertRaisesRegex(capabilities.CapabilityError, "aplicación"):
            capabilities.run(self.config, "apps.launch", {"app": "  "})


class DeclaracionEnLosDosLados(TestCase):
    def test_capacidad_publicada_y_clasificada_como_escritorio(self):
        self.assertIn("apps.launch", capabilities.HANDLERS)
        self.assertIn("apps.launch", nodes.CAPABILITIES)
        self.assertIn("apps.launch", nodes.CAPACIDADES_ESCRITORIO)
        self.assertNotIn("apps.launch", nodes.CAPACIDADES_LECTURA)
        self.assertIn("devices.launch_app", tools.PRIMITIVES)

    def test_el_riesgo_sube_solo_si_hay_contenido_contaminado(self):
        with patch.object(nodes.taint.registro, "contaminado", return_value=False):
            self.assertEqual(nodes.evaluar_riesgo("u", "apps.launch", {}), "bajo")
        with patch.object(nodes.taint.registro, "contaminado", return_value=True):
            self.assertEqual(nodes.evaluar_riesgo("u", "apps.launch", {}), "medio")


class PrimitivaPublica(IsolatedAsyncioTestCase):
    async def test_envia_solo_app_y_no_encola_si_el_pc_esta_apagado(self):
        node = {
            "id": "node-1",
            "user_id": "u",
            "nombre": "PC",
            "plataforma": "Windows 11",
            "estado": "activo",
            "shell_habilitado": 1,
            "capacidades": ["apps.launch"],
            "last_seen": None,
            "created_at": 0.0,
        }
        outcome = {
            "estado": "ok",
            "resultado": {
                "status": "launched",
                "app": {"id": "app_1", "label": "Spotify"},
                "node_execution_ms": 7,
            },
        }
        with (
            patch.object(tools, "resolve_device", return_value=node),
            patch.object(nodes, "dispatch", AsyncMock(return_value=outcome)) as dispatch,
        ):
            primitive = tools.PRIMITIVES["devices.launch_app"]
            parsed = primitive.input_model.model_validate({"app": "Spotify"})
            result = await primitive.handler({"id": "u"}, parsed)

        dispatch.assert_awaited_once_with(
            {"id": "u"},
            node,
            "apps.launch",
            {"app": "Spotify"},
            queue_if_offline=False,
        )
        self.assertEqual(result["result"]["status"], "launched")
        self.assertGreaterEqual(result["node_dispatch_ms"], 0)

    async def test_campos_de_shell_ruta_o_argumentos_son_invalidos(self):
        primitive = tools.PRIMITIVES["devices.launch_app"]
        for extra in (
            {"path": r"C:\\Windows\\calc.exe"},
            {"arguments": ["--private"]},
            {"command": "calc.exe"},
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(Exception):
                    primitive.input_model.model_validate({"app": "Spotify", **extra})


class AuditoriaDeLaPrimitiva(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.patches = [
            patch.object(settings, "db_path", str(root / "morgana.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
        ]
        for setting_patch in self.patches:
            setting_patch.start()
            self.addCleanup(setting_patch.stop)
        db.init_db()
        self.user = db.get_or_create_user("ruben")

    def test_tools_execute_registra_el_lanzamiento(self):
        node = {
            "id": "node-1",
            "user_id": self.user["id"],
            "nombre": "PC",
            "plataforma": "Windows 11",
            "estado": "activo",
            "shell_habilitado": 1,
            "capacidades": ["apps.launch"],
            "last_seen": None,
            "created_at": 0.0,
        }
        outcome = {
            "estado": "ok",
            "resultado": {
                "status": "launched",
                "app": {"id": "app_1", "label": "Spotify"},
                "node_execution_ms": 4,
            },
        }
        with (
            patch.object(tools, "resolve_device", return_value=node),
            patch.object(nodes, "dispatch", AsyncMock(return_value=outcome)),
        ):
            execution = asyncio.run(
                tools.execute("devices.launch_app", self.user, {"app": "Spotify"})
            )

        self.assertEqual(execution["status"], "succeeded")
        invocations = db.list_tool_invocations(
            "devices.launch_app", self.user["id"], 10
        )
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0]["status"], "succeeded")


if __name__ == "__main__":
    import unittest

    unittest.main()

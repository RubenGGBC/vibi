"""Con qué intérprete ejecuta comandos la capacidad `shell.run`.

Importa porque es la vía de la ejecución remota entre dispositivos, y porque
en Windows equivocarse de intérprete no da un error claro: da un comando que
«no se reconoce» y un modelo convencido de que el sistema está roto.
"""
from __future__ import annotations

import platform
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import capabilities, system_shell  # noqa: E402
from vibi_node.config import NodeConfig  # noqa: E402


class ShellRun(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.config = NodeConfig(
            url="https://vibi.local",
            node_id="n",
            token="t",
            nombre="bench",
            projects_root=self.tempdir.name,
            inbox_root=self.tempdir.name,
        )

    def test_usa_el_mismo_interprete_que_el_mcp(self):
        """No hay dos formas de ejecutar un comando en esta máquina.

        `system_shell.interprete()` ya decidió cuál es —y documenta por qué—;
        esta capacidad tiene que usar esa misma, no `shell=True`.
        """
        with patch.object(capabilities.subprocess, "run") as corrido:
            corrido.return_value.returncode = 0
            corrido.return_value.stdout = ""
            corrido.return_value.stderr = ""
            capabilities.run(self.config, "shell.run", {"comando": "algo"})

        argumentos, opciones = corrido.call_args
        self.assertEqual(argumentos[0], [*system_shell.interprete(), "algo"])
        self.assertNotIn(
            "shell", opciones, "`shell=True` es cmd.exe en Windows"
        )


@skipUnless(platform.system() == "Windows", "el intérprete solo importa aquí")
class ShellRunEnWindows(TestCase):
    """Contra el intérprete de verdad: lo único que delata el fallo."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.config = NodeConfig(
            url="https://vibi.local",
            node_id="n",
            token="t",
            nombre="bench",
            projects_root=self.tempdir.name,
            inbox_root=self.tempdir.name,
        )

    def _correr(self, comando: str) -> dict:
        return capabilities.run(self.config, "shell.run", {"comando": comando})

    def test_un_cmdlet_se_ejecuta(self):
        resultado = self._correr("Get-Date -Format yyyy")
        self.assertEqual(
            resultado["codigo"], 0, f"stderr: {resultado['stderr'][:200]}"
        )
        self.assertRegex(resultado["stdout"].strip(), r"^\d{4}$")

    def test_una_tuberia_de_objetos_se_ejecuta(self):
        resultado = self._correr(
            "Get-Process | Select-Object -First 1 -ExpandProperty ProcessName"
        )
        self.assertEqual(
            resultado["codigo"], 0, f"stderr: {resultado['stderr'][:200]}"
        )
        self.assertTrue(resultado["stdout"].strip())

    def test_lo_de_siempre_sigue_funcionando(self):
        resultado = self._correr("echo hola")
        self.assertEqual(resultado["codigo"], 0)
        self.assertIn("hola", resultado["stdout"])

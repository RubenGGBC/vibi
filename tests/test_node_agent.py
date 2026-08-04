"""Pruebas del agente que corre en la máquina del usuario.

El agente vive fuera de `app/` porque se instala solo, sin el servidor.
Estas pruebas lo tratan igual: importándolo desde `agent/`.
"""
import asyncio
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, skipIf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import websockets  # noqa: E402

from morgana_node import capabilities, client  # noqa: E402
from morgana_node.config import (  # noqa: E402
    NodeConfig,
    load,
    save,
    websocket_url,
)


def _config(root: Path) -> NodeConfig:
    return NodeConfig(
        url="https://morgana.local",
        node_id="nodo-1",
        token="nodo-1.secreto",
        nombre="MacBook Pro",
        projects_root=str(root),
    )


class Credencial(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.path = self.root / "node.json"

    def test_guardar_y_releer(self):
        config = _config(self.root)
        save(config, self.path)
        self.assertEqual(load(self.path), config)

    @skipIf(os.name == "nt", "Windows no aplica permisos POSIX")
    def test_el_token_no_queda_legible_por_otros(self):
        save(_config(self.root), self.path)
        modo = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(modo, 0o600)

    def test_sin_credencial_no_revienta(self):
        self.assertIsNone(load(self.root / "no-existe.json"))

    def test_credencial_incompleta_lo_dice_claro(self):
        self.path.write_text(json.dumps({"url": "https://x"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load(self.path)

    def test_url_del_websocket(self):
        self.assertEqual(
            websocket_url("https://mi-pc.ts.net"), "wss://mi-pc.ts.net/api/nodos/ws"
        )
        self.assertEqual(
            websocket_url("http://localhost:8000/"),
            "ws://localhost:8000/api/nodos/ws",
        )
        with self.assertRaises(ValueError):
            websocket_url("ftp://mi-pc")


class Capacidades(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.config = _config(self.root)

    def test_ping_dice_quien_es(self):
        resultado = capabilities.run(self.config, "ping", {})
        self.assertEqual(resultado["nodo"], "MacBook Pro")
        self.assertIn("hostname", resultado)

    def test_una_capacidad_desconocida_no_se_ejecuta(self):
        with self.assertRaises(capabilities.CapabilityError):
            capabilities.run(self.config, "shell.run", {"cmd": "rm -rf /"})

    def test_lista_carpetas_ignorando_ocultas_y_archivos(self):
        (self.root / "morgana").mkdir()
        (self.root / "morgana" / ".git").mkdir()
        (self.root / "tesis").mkdir()
        (self.root / ".cache").mkdir()
        (self.root / "notas.txt").write_text("hola", encoding="utf-8")

        resultado = capabilities.run(self.config, "projects.list", {})

        self.assertEqual(
            [p["nombre"] for p in resultado["proyectos"]], ["morgana", "tesis"]
        )
        self.assertTrue(resultado["proyectos"][0]["git"])
        self.assertFalse(resultado["proyectos"][1]["git"])
        self.assertEqual(resultado["total"], 2)

    def test_no_se_filtran_rutas_absolutas(self):
        (self.root / "morgana").mkdir()
        resultado = capabilities.run(self.config, "projects.list", {})
        self.assertNotIn(str(self.root), json.dumps(resultado))

    def test_raiz_inexistente_da_un_error_util(self):
        config = _config(self.root / "no-existe")
        with self.assertRaises(capabilities.CapabilityError) as capturado:
            capabilities.run(config, "projects.list", {})
        self.assertIn("no existe", str(capturado.exception))

    def test_no_devuelve_una_lista_infinita(self):
        for indice in range(capabilities.MAX_PROJECTS + 10):
            (self.root / f"proyecto-{indice:03d}").mkdir()
        resultado = capabilities.run(self.config, "projects.list", {})
        self.assertEqual(resultado["total"], capabilities.MAX_PROJECTS)


class SesionContraUnServidorFalso(TestCase):
    """El bucle del agente contra un WebSocket de mentira."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        (self.root / "morgana").mkdir()
        self.recibido: list[dict] = []

    def _ejecutar(self, guion: list[dict]) -> None:
        """Levanta un servidor que manda `guion` y anota lo que le llega."""

        async def servidor(connection):
            self.recibido.append(json.loads(await connection.recv()))
            await connection.send(
                json.dumps({"tipo": "conexion_lista", "nombre": "MacBook Pro"})
            )
            for mensaje in guion:
                await connection.send(json.dumps(mensaje))
            for _ in guion:
                self.recibido.append(json.loads(await connection.recv()))
            # Al cerrar aquí, el bucle del agente termina y `_sesion` vuelve:
            # es la forma limpia de cortar una sesión que si no es infinita.
            await connection.close()

        async def escenario():
            async with websockets.serve(servidor, "127.0.0.1", 0) as server:
                puerto = server.sockets[0].getsockname()[1]
                config = NodeConfig(
                    url=f"http://127.0.0.1:{puerto}",
                    node_id="nodo-1",
                    token="nodo-1.secreto",
                    nombre="MacBook Pro",
                    projects_root=str(self.root),
                )
                await asyncio.wait_for(client._sesion(config), timeout=5)

        asyncio.run(escenario())

    def test_se_presenta_con_su_token_y_capacidades(self):
        self._ejecutar([])
        saludo = self.recibido[0]
        self.assertEqual(saludo["tipo"], "hola")
        self.assertEqual(saludo["token"], "nodo-1.secreto")
        self.assertEqual(saludo["capacidades"], ["ping", "projects.list"])

    def test_ejecuta_una_orden_y_devuelve_el_resultado(self):
        self._ejecutar(
            [
                {
                    "tipo": "orden",
                    "id": "orden-1",
                    "capability": "projects.list",
                    "arguments": {},
                }
            ]
        )
        respuesta = self.recibido[1]
        self.assertEqual(respuesta["tipo"], "resultado")
        self.assertEqual(respuesta["id"], "orden-1")
        self.assertEqual(respuesta["estado"], "ok")
        self.assertEqual(
            [p["nombre"] for p in respuesta["resultado"]["proyectos"]], ["morgana"]
        )

    def test_una_orden_que_el_nodo_no_conoce_vuelve_como_error(self):
        self._ejecutar(
            [
                {
                    "tipo": "orden",
                    "id": "orden-2",
                    "capability": "shell.run",
                    "arguments": {"cmd": "whoami"},
                }
            ]
        )
        respuesta = self.recibido[1]
        self.assertEqual(respuesta["estado"], "error")
        self.assertIn("no sabe hacer", respuesta["resultado"]["error"])

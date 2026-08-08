"""El puente MCP: cómo se le publican a `agy` las capacidades de Morgana."""
import json
import unittest
import unittest.mock
from unittest.mock import patch

from app import tools
from app.executors import agy_mcp, antigravity_chat


class NombresDeLasHerramientas(unittest.TestCase):
    """Los ids llevan punto y los clientes MCP prefieren guion bajo."""

    def test_el_punto_se_convierte_en_guion_bajo(self):
        self.assertEqual(agy_mcp.nombre_mcp("files.search"), "files_search")

    def test_se_puede_volver_al_id_original(self):
        for tool_id in tools.PRIMITIVES:
            self.assertEqual(
                agy_mcp.id_primitiva(agy_mcp.nombre_mcp(tool_id)), tool_id
            )

    def test_dos_capacidades_no_se_pisan_el_nombre(self):
        nombres = [agy_mcp.nombre_mcp(tool_id) for tool_id in tools.PRIMITIVES]
        self.assertEqual(len(nombres), len(set(nombres)))

    def test_un_nombre_inventado_no_resuelve(self):
        """Lo que llega por MCP viene de fuera: no se traduce a ciegas."""
        with self.assertRaises(tools.ToolNotFound):
            agy_mcp.id_primitiva("os_system")


class LoQueVeElModelo(unittest.TestCase):
    def test_la_descripcion_avisa_de_los_efectos(self):
        """Saber que algo escribe o sale a la red evita usarlo por descuido."""
        primitiva = tools.PRIMITIVES["devices.shell"]

        descripcion = agy_mcp._descripcion(primitiva)

        self.assertIn(primitiva.description, descripcion)
        for efecto in primitiva.effects:
            self.assertIn(efecto, descripcion)

    def test_sin_efectos_la_descripcion_va_limpia(self):
        primitiva = tools.PRIMITIVES["system.health"]
        if primitiva.effects:
            self.skipTest("system.health ha dejado de ser inocua")

        self.assertEqual(agy_mcp._descripcion(primitiva), primitiva.description)


class EjecutarDelegandoEnMorgana(unittest.IsolatedAsyncioTestCase):
    """El puente no ejecuta: se lo pide al servidor.

    Corre como proceso hijo de `agy`, y ahí no existe el estado vivo de
    Morgana: qué máquinas están conectadas y los WebSockets por los que se les
    manda algo viven en memoria de uvicorn. Ejecutando aquí, todo `devices.*`
    vería el mundo apagado.
    """

    async def test_sin_token_no_llama_a_nadie(self):
        with patch.dict("os.environ", {agy_mcp.VARIABLE_TOKEN: ""}, clear=False):
            resultado = await agy_mcp.ejecutar("devices.list", {})

        self.assertIn("error", resultado)

    async def test_llama_al_endpoint_con_el_token(self):
        respuesta = unittest.mock.Mock(status_code=200)
        respuesta.json.return_value = {"status": "succeeded"}
        cliente = unittest.mock.AsyncMock()
        cliente.__aenter__.return_value.post.return_value = respuesta

        with patch.dict(
            "os.environ",
            {agy_mcp.VARIABLE_TOKEN: "jwt-de-prueba", agy_mcp.VARIABLE_URL: "http://m:8000"},
            clear=False,
        ), patch.object(agy_mcp.httpx, "AsyncClient", return_value=cliente):
            resultado = await agy_mcp.ejecutar("devices.list", {"a": 1})

        llamada = cliente.__aenter__.return_value.post.await_args
        self.assertEqual(llamada.args[0], "http://m:8000/api/herramientas/devices.list/ejecutar")
        self.assertEqual(llamada.kwargs["json"], {"arguments": {"a": 1}})
        self.assertEqual(
            llamada.kwargs["headers"]["Authorization"], "Bearer jwt-de-prueba"
        )
        self.assertEqual(resultado, {"status": "succeeded"})

    async def test_un_rechazo_se_devuelve_como_dato_no_como_caida(self):
        """El modelo tiene que poder leer el error y corregir."""
        respuesta = unittest.mock.Mock(status_code=422, text="Argumentos inválidos")
        respuesta.json.return_value = {"error": "Argumentos inválidos"}
        cliente = unittest.mock.AsyncMock()
        cliente.__aenter__.return_value.post.return_value = respuesta

        with patch.dict(
            "os.environ", {agy_mcp.VARIABLE_TOKEN: "jwt"}, clear=False
        ), patch.object(agy_mcp.httpx, "AsyncClient", return_value=cliente):
            resultado = await agy_mcp.ejecutar("files.read", {})

        self.assertEqual(resultado["error"], "Argumentos inválidos")
        self.assertEqual(resultado["status"], 422)


class DeclararElServidorEnAgy(unittest.TestCase):
    def _config(self, home):
        return home / ".gemini" / "config" / "mcp_config.json"

    def test_escribe_la_configuracion_con_el_usuario_dentro(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as home:
            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                antigravity_chat.escribir_configuracion_mcp("u-123")

            guardado = json.loads(self._config(Path(home)).read_text(encoding="utf-8"))

        morgana = guardado["mcpServers"]["morgana"]
        self.assertTrue(morgana["args"][0].endswith("agy_mcp.py"))
        # Va un token, no el secreto con el que se firma.
        self.assertTrue(morgana["env"]["MORGANA_TOKEN"])
        self.assertNotIn("JWT_SECRET", json.dumps(morgana))
        # Y apunta al propio contenedor, no a la URL pública.
        self.assertIn("127.0.0.1", morgana["env"]["MORGANA_URL"])

    def test_respeta_los_servidores_que_ya_hubiera(self):
        """La configuración es global: puede haber cosas del usuario ahí."""
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as home:
            destino = self._config(Path(home))
            destino.parent.mkdir(parents=True)
            destino.write_text(
                json.dumps({"mcpServers": {"otro": {"command": "algo"}}}),
                encoding="utf-8",
            )

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                antigravity_chat.escribir_configuracion_mcp("u-123")

            guardado = json.loads(destino.read_text(encoding="utf-8"))

        self.assertIn("otro", guardado["mcpServers"])
        self.assertIn("morgana", guardado["mcpServers"])

    def test_una_configuracion_corrupta_no_impide_arrancar(self):
        """Sin tools Morgana conversa igual; sin conversación, no."""
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as home:
            destino = self._config(Path(home))
            destino.parent.mkdir(parents=True)
            destino.write_text("{esto no es json", encoding="utf-8")

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                antigravity_chat.escribir_configuracion_mcp("u-123")


if __name__ == "__main__":
    unittest.main()

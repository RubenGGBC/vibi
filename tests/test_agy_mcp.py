"""El puente MCP: cómo se le publican a `agy` las capacidades de Vibi."""
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


class LasQueAgyYaSabeHacerPorOtraVia(unittest.TestCase):
    """No se le publican dos caminos para la misma capacidad.

    `devices.shell` y `devices.files_search` llegaban al modelo a la vez que
    `pc_ejecutar` y `pc_buscar`, que hacen lo mismo sobre la misma máquina. Y
    no salía gratis: en la traza del 19/08/2026 se ve al modelo gastando ocho
    pasos —`view_file` de tres esquemas, `list_dir` del directorio MCP,
    `call_mcp_tool pc/info`— averiguando cuál de sus caminos usar, antes de
    empezar siquiera con lo que se le había pedido. Ese turno murió a los 60 s.

    La primitiva no se borra: la PWA, Telegram y el router siguen llamándola.
    Lo que se quita es el camino duplicado delante del modelo.

    **Pero solo mientras el otro camino esté de verdad delante.** La poda era
    incondicional y eso abrió un agujero al pasar el core a nativo: sin
    servidor `pc` que declarar, `devices.files_search` se ocultaba igual y su
    sustituto no existía. El modelo se quedaba sin la búsqueda por el índice
    de Windows —482 ms— y con el recorrido de carpetas por `run_command`, que
    en este equipo da mediana de 300 segundos.
    """

    def _publicadas(self, pc: bool) -> set[str]:
        with patch.object(agy_mcp, "pc_declarado", return_value=pc):
            return set(agy_mcp.tools_publicadas())

    def test_con_pc_delante_no_se_publica_lo_que_pc_ya_cubre(self):
        publicadas = self._publicadas(pc=True)

        self.assertNotIn("devices.shell", publicadas)
        self.assertNotIn("devices.files_search", publicadas)

    def test_sin_pc_la_busqueda_por_el_indice_vuelve(self):
        """Es la única que tiene: `grep_search` busca DENTRO de una carpeta."""
        self.assertIn("devices.files_search", self._publicadas(pc=False))

    def test_sin_pc_la_terminal_supervisada_vuelve(self):
        """`run_command` no promociona a segundo plano: no es sustituto."""
        publicadas = self._publicadas(pc=False)
        self.assertIn("devices.shell", publicadas)
        self.assertIn("devices.shell_status", publicadas)
        self.assertIn("devices.shell_stop", publicadas)

    def test_lo_dice_quien_monta_la_configuracion(self):
        """El puente es un proceso hijo y no ve qué servidores se declararon."""
        from app.executors import agy_mcp_config

        with patch.dict(
            "os.environ", {agy_mcp_config.VARIABLE_PC_MCP: "1"}, clear=False
        ):
            self.assertTrue(agy_mcp.pc_declarado())
        with patch.dict(
            "os.environ", {agy_mcp_config.VARIABLE_PC_MCP: ""}, clear=False
        ):
            self.assertFalse(agy_mcp.pc_declarado())

    def test_las_primitivas_siguen_existiendo_para_el_resto_del_sistema(self):
        self.assertIn("devices.shell", tools.PRIMITIVES)
        self.assertIn("devices.files_search", tools.PRIMITIVES)

    def test_lo_que_no_duplica_nada_se_sigue_publicando(self):
        publicadas = set(agy_mcp.tools_publicadas())

        # El escritorio y los archivos de Vibi no tienen otro camino.
        self.assertIn("devices.ui_snapshot", publicadas)
        self.assertIn("devices.screenshot", publicadas)
        self.assertIn("files.read", publicadas)

    def test_una_oculta_sigue_siendo_ejecutable_si_la_pide(self):
        """Ocultarla no es prohibirla: el resto del sistema la sigue usando."""
        self.assertEqual(agy_mcp.id_primitiva("devices_shell"), "devices.shell")


class LaBusquedaWebLaPoneAgy(unittest.TestCase):
    """Exa sobra: `agy` trae `search_web` propio y lo usa por su cuenta.

    En la traza del 19/08/2026 el modelo hizo cinco `search_web` nativos
    seguidos con Exa declarado y disponible, sin tocarlo ni una vez. Era un
    servidor MCP arrancándose en cada sesión, dos esquemas más delante del
    modelo y una clave de API pagándose, para una capacidad que ya venía
    incluida.
    """

    def test_no_se_declara_nunca(self):
        from app.executors import agy_mcp_config

        class _Ajustes:
            google_mcp_servers = ""
            google_mcp_client_id = ""
            google_mcp_client_secret = ""

        servidores = agy_mcp_config.construir_servidores(
            "u-1", "", _Ajustes(), ""
        )

        self.assertIsNone(servidores.get(agy_mcp_config.SERVIDOR_EXA))

    def test_su_entrada_vieja_se_borra_en_vez_de_heredarse(self):
        from app.executors import agy_mcp_config

        self.assertIn(
            agy_mcp_config.SERVIDOR_EXA, agy_mcp_config.SERVIDORES_HEREDADOS
        )


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


class EjecutarDelegandoEnVibi(unittest.IsolatedAsyncioTestCase):
    """El puente no ejecuta: se lo pide al servidor.

    Corre como proceso hijo de `agy`, y ahí no existe el estado vivo de
    Vibi: qué máquinas están conectadas y los WebSockets por los que se les
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


class ElPlaywrightQuePongaElUsuarioSeRespeta(unittest.TestCase):
    """Si lo declara él a mano, no se lo pisamos.

    Vibi arranca el navegador en el nodo y lo declara por `serverUrl`; cuando no
    puede —el nodo desconectado, el navegador sin puerto de depuración—, la
    entrada se borraba. Y borrarla se llevaba por delante la que el usuario
    hubiera puesto por su cuenta con `npx @playwright/mcp`, que es un montaje
    perfectamente válido y el único que le funciona a él.

    Se distinguen por la forma, que es fiable: la nuestra siempre es un
    `serverUrl` al nodo; la suya la lanza `agy` como proceso hijo (`command`).
    """

    def _config(self, home):
        return home / ".gemini" / "config" / "mcp_config.json"

    def _escribir(self, home, entrada):
        destino = self._config(home)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps({"mcpServers": {"playwright": entrada}}), encoding="utf-8"
        )
        return destino

    def test_el_suyo_con_command_sobrevive(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        suyo = {"command": "npx", "args": ["@playwright/mcp@latest"]}
        with TemporaryDirectory() as home:
            destino = self._escribir(Path(home), suyo)

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                # Sin URL de navegador: es cuando antes se borraba.
                antigravity_chat.escribir_configuracion_mcp("u-123", "")

            guardado = json.loads(destino.read_text(encoding="utf-8"))

        self.assertEqual(guardado["mcpServers"]["playwright"], suyo)

    def test_el_nuestro_si_se_retira_cuando_no_hay_navegador(self):
        """Una URL a un nodo que ya no sirve nada le cuesta a `agy` el arranque
        entero descubriéndolo."""
        from tempfile import TemporaryDirectory
        from pathlib import Path

        nuestro = {"serverUrl": "http://127.0.0.1:8931/mcp"}
        with TemporaryDirectory() as home:
            destino = self._escribir(Path(home), nuestro)

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                antigravity_chat.escribir_configuracion_mcp("u-123", "")

            guardado = json.loads(destino.read_text(encoding="utf-8"))

        self.assertNotIn("playwright", guardado["mcpServers"])

    def test_con_navegador_nuestro_gana_la_url(self):
        """Si Vibi consigue levantarlo, esa es la buena."""
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as home:
            destino = self._escribir(Path(home), {"command": "npx", "args": []})

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                antigravity_chat.escribir_configuracion_mcp(
                    "u-123", "http://host.docker.internal:8931/mcp"
                )

            guardado = json.loads(destino.read_text(encoding="utf-8"))

        self.assertEqual(
            guardado["mcpServers"]["playwright"],
            {"serverUrl": "http://host.docker.internal:8931/mcp"},
        )


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

        vibi = guardado["mcpServers"]["vibi"]
        self.assertTrue(vibi["args"][0].endswith("agy_mcp.py"))
        # Va un token, no el secreto con el que se firma.
        self.assertTrue(vibi["env"]["VIBI_TOKEN"])
        self.assertNotIn("JWT_SECRET", json.dumps(vibi))
        # Y apunta al propio contenedor, no a la URL pública.
        self.assertIn("127.0.0.1", vibi["env"]["VIBI_URL"])

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
        self.assertIn("vibi", guardado["mcpServers"])

    def test_borra_el_servidor_del_nombre_viejo_del_proyecto(self):
        """El proyecto se llamó `morgana` y esa entrada sobrevivió al cambio.

        Apunta a `/srv/morgana`, que ya no existe, y `agy` conserva sus 28
        esquemas en disco: el modelo sigue viendo duplicada media caja de
        herramientas. Como no está entre las que gestionamos, el merge la
        trataba como si fuera del usuario y no se borraba nunca.
        """
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as home:
            destino = self._config(Path(home))
            destino.parent.mkdir(parents=True)
            destino.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "morgana": {
                                "command": "/usr/local/bin/python3.12",
                                "args": ["/srv/morgana/app/executors/agy_mcp.py"],
                            },
                            "otro": {"command": "algo"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                antigravity_chat.escribir_configuracion_mcp("u-123")

            guardado = json.loads(destino.read_text(encoding="utf-8"))

        self.assertNotIn("morgana", guardado["mcpServers"])
        # Y sin llevarse por delante ni lo nuestro ni lo suyo.
        self.assertIn("vibi", guardado["mcpServers"])
        self.assertIn("otro", guardado["mcpServers"])

    def test_borra_los_esquemas_que_agy_cacheo_del_nombre_viejo(self):
        """Quitarlo del config no basta: `agy` los guarda aparte en disco.

        Mientras el directorio siga ahí, el modelo puede seguir llamando a
        herramientas de un servidor que ya no arranca.
        """
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as home:
            cache = (
                Path(home) / ".gemini" / "antigravity-cli" / "mcp" / "morgana"
            )
            cache.mkdir(parents=True)
            (cache / "devices_click.json").write_text("{}", encoding="utf-8")
            viva = cache.parent / "vibi"
            viva.mkdir()
            (viva / "devices_click.json").write_text("{}", encoding="utf-8")

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                antigravity_chat.escribir_configuracion_mcp("u-123")

            self.assertFalse(cache.exists())
            self.assertTrue(viva.exists())


    def test_borra_los_esquemas_de_las_tools_que_dejamos_de_publicar(self):
        """Dejar de publicarlas no basta: `agy` ya tenía su esquema guardado.

        Visto en el contenedor el 19/08/2026 justo después de desplegar la
        poda: el servidor `vibi` ya no las publicaba, pero
        `mcp/vibi/devices_shell.json` seguía en disco con fecha de la mañana.
        Es el mismo fallo que dejó vivo al servidor del nombre viejo, un nivel
        más abajo: mientras el esquema esté ahí, el modelo puede llamarla.
        """
        from tempfile import TemporaryDirectory
        from pathlib import Path

        from app.executors import agy_mcp_config

        with TemporaryDirectory() as home:
            cache = Path(home) / ".gemini" / "antigravity-cli" / "mcp" / "vibi"
            cache.mkdir(parents=True)
            for tool_id in agy_mcp_config.CUBIERTAS_POR_EL_SISTEMA:
                (cache / f"{agy_mcp.nombre_mcp(tool_id)}.json").write_text(
                    "{}", encoding="utf-8"
                )
            superviviente = cache / "files_read.json"
            superviviente.write_text("{}", encoding="utf-8")

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                # Con el servidor del ordenador declarado, que es cuando se
                # podan las dos.
                antigravity_chat.escribir_configuracion_mcp(
                    "u-123", sistema_url="http://portatil.ts.net:8933/x/mcp"
                )

            for tool_id in agy_mcp_config.CUBIERTAS_POR_EL_SISTEMA:
                esquema = cache / f"{agy_mcp.nombre_mcp(tool_id)}.json"
                self.assertFalse(esquema.exists(), f"{tool_id} sigue publicada")
            self.assertTrue(superviviente.exists(), "se llevó por delante otra")

    def test_no_borra_el_esquema_de_lo_que_vuelve_a_publicarse(self):
        """Sin servidor `pc`, `devices_files_search` se publica otra vez.

        Y entonces borrarle el esquema es el error simétrico del que este
        método arregla: `agy` tendría que volver a pedírselo, y hasta que lo
        hiciera el modelo no vería la única búsqueda por índice que tiene.
        """
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as home:
            cache = Path(home) / ".gemini" / "antigravity-cli" / "mcp" / "vibi"
            cache.mkdir(parents=True)
            busqueda = cache / "devices_files_search.json"
            busqueda.write_text("{}", encoding="utf-8")
            shell = cache / "devices_shell.json"
            shell.write_text("{}", encoding="utf-8")

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                # Sin `sistema_url`: no hay servidor `pc` que declarar.
                antigravity_chat.escribir_configuracion_mcp("u-123")

            self.assertTrue(busqueda.exists(), "se la ha llevado sin sustituto")
            self.assertTrue(shell.exists(), "la terminal supervisada vuelve sin pc")

    def test_una_configuracion_corrupta_no_impide_arrancar(self):
        """Sin tools Vibi conversa igual; sin conversación, no."""
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

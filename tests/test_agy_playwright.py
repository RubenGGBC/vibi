"""El navegador visible: quién lo enciende y cómo se le declara a `agy`.

Lo que se prueba aquí no es Playwright —ese es código de otros y ya viene
probado— sino las dos costuras nuestras: que el servidor se levanta en la
máquina del usuario y no en el contenedor, y que `agy` acaba sabiendo dónde
está sin que una avería en el camino le deje sin conversación.
"""
import json
import socket
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent.vibi_node import browser_mcp, capabilities
from app import nodes
from app.executors import antigravity_chat


class LaCapacidadEstaDeclaradaEnLosDosLados(unittest.TestCase):
    """El nodo y el servidor validan por separado: ninguno se fía del otro."""

    def test_el_nodo_sabe_hacerla(self):
        self.assertIn("browser.mcp", capabilities.HANDLERS)

    def test_el_servidor_la_acepta(self):
        self.assertIn("browser.mcp", nodes.CAPABILITIES)

    def test_cuenta_como_algo_que_pasa_delante_de_ti(self):
        """Abre una ventana y se deshace cerrándola, como `browser.open`."""
        self.assertIn("browser.mcp", nodes.CAPACIDADES_ESCRITORIO)

    def test_el_interruptor_del_dispositivo_la_apaga(self):
        """No es de lectura, así que respeta `shell_habilitado`."""
        self.assertNotIn("browser.mcp", nodes.CAPACIDADES_LECTURA)


class ArrancarElServidorEnElPc(unittest.TestCase):
    def test_si_el_puerto_ya_contesta_no_lanza_otro(self):
        """La llamada se repite en cada sesión de `agy`: tiene que ser barata.

        Con perfil propio, y no es un detalle: sin él la prueba lee la marca
        del `%LOCALAPPDATA%` de quien la ejecuta y acaba intentando cerrarle el
        servidor que tenga en pie. Un test no toca la máquina de nadie.
        """
        with TemporaryDirectory() as perfil:
            with patch.object(browser_mcp, "escuchando", return_value=True), \
                 patch.object(browser_mcp, "_lanzar") as lanzar:
                resultado = browser_mcp.arrancar(puerto=8931, perfil=Path(perfil))

        lanzar.assert_not_called()
        self.assertEqual(resultado["estado"], "ok")
        self.assertFalse(resultado["arrancado_ahora"])

    def test_un_servidor_ajeno_que_rechaza_el_host_se_denuncia(self):
        """Reutilizarlo daría un 403 en cada turno, sin decir por qué."""
        with TemporaryDirectory() as perfil:
            with patch.object(browser_mcp, "escuchando", return_value=True), \
                 patch.object(browser_mcp, "acepta_host", return_value=False), \
                 patch.object(browser_mcp, "_lanzar") as lanzar:
                with self.assertRaises(browser_mcp.BrowserMCPError) as fallo:
                    browser_mcp.arrancar(
                        8931,
                        perfil=Path(perfil),
                        hosts_permitidos="host.docker.internal",
                    )

        lanzar.assert_not_called()
        self.assertIn("ocupado", str(fallo.exception))

    def test_el_comando_lleva_puerto_navegador_y_perfil(self):
        with patch.object(browser_mcp, "_npx", return_value="npx"):
            argv = browser_mcp.comando(9000, "chrome", Path("/tmp/perfil"), "0.0.0.0")

        self.assertIn(browser_mcp.PAQUETE, argv)
        self.assertEqual(argv[argv.index("--port") + 1], "9000")
        self.assertEqual(argv[argv.index("--browser") + 1], "chrome")
        self.assertEqual(argv[argv.index("--host") + 1], "0.0.0.0")
        self.assertIn("perfil", argv[argv.index("--user-data-dir") + 1])

    def test_los_volcados_no_caen_donde_se_lanzó(self):
        """Si no, acaban en el repo que tuvieras abierto al arrancar."""
        with patch.object(browser_mcp, "_npx", return_value="npx"):
            argv = browser_mcp.comando(8931, "chrome", Path("/tmp/perfil"), "0.0.0.0")

        salidas = argv[argv.index("--output-dir") + 1]
        self.assertIn("perfil", salidas)

    def test_no_se_abre_a_la_red_por_defecto(self):
        """Docker Desktop hace de intermediario: el contenedor llega igual.

        Y como el servidor no pide credenciales, quien alcance el puerto pilota
        el navegador con las sesiones que haya iniciadas en su perfil. Abrirlo
        y taparlo con el cortafuegos era peor que no abrirlo.
        """
        self.assertEqual(browser_mcp.HOST_POR_DEFECTO, "127.0.0.1")

    def test_el_host_permitido_se_declara_con_puerto_y_sin_el(self):
        """Un cliente manda `Host: nombre:puerto`; sin esa forma es un 403."""
        with patch.object(browser_mcp, "_npx", return_value="npx"):
            argv = browser_mcp.comando(
                8931, "chrome", Path("."), "0.0.0.0", "host.docker.internal"
            )

        permitidos = argv[argv.index("--allowed-hosts") + 1]
        self.assertIn("host.docker.internal:8931", permitidos)
        self.assertIn("host.docker.internal", permitidos.split(","))

    def test_no_se_abre_a_cualquiera(self):
        """`*` apagaría la defensa contra DNS rebinding."""
        with patch.object(browser_mcp, "_npx", return_value="npx"):
            argv = browser_mcp.comando(
                8931, "chrome", Path("."), "0.0.0.0", "host.docker.internal"
            )

        self.assertNotIn("*", argv[argv.index("--allowed-hosts") + 1])

    def test_sin_hosts_permitidos_no_se_pasa_la_opcion(self):
        """Su valor por defecto ya cubre el caso de trabajar en local."""
        with patch.object(browser_mcp, "_npx", return_value="npx"):
            argv = browser_mcp.comando(8931, "chrome", Path("."), "0.0.0.0")

        self.assertNotIn("--allowed-hosts", argv)

    def test_un_host_que_ya_trae_puerto_no_se_duplica(self):
        formas = browser_mcp.hosts_con_puerto("vibi:8931", 8931)

        self.assertEqual(formas.split(","), ["vibi", "vibi:8931"])

    def test_sin_node_lo_dice_en_vez_de_reventar(self):
        with patch.dict("os.environ", {browser_mcp.VARIABLE_NPX: ""}, clear=False), \
             patch.object(browser_mcp.shutil, "which", return_value=None):
            with self.assertRaises(browser_mcp.BrowserMCPError) as fallo:
                browser_mcp.comando(8931, "chrome", Path("."), "0.0.0.0")

        self.assertIn("npx", str(fallo.exception))

    def test_la_ruta_declarada_gana_al_path(self):
        """Con nvm, la versión activa puede no traer npm y otra sí."""
        with patch.dict(
            "os.environ", {browser_mcp.VARIABLE_NPX: __file__}, clear=False
        ), patch.object(browser_mcp.shutil, "which", return_value="otro-npx"):
            self.assertEqual(browser_mcp._npx(), __file__)

    def test_una_ruta_declarada_que_no_existe_se_denuncia(self):
        with patch.dict(
            "os.environ", {browser_mcp.VARIABLE_NPX: "C:/no/existe/npx.cmd"}, clear=False
        ):
            with self.assertRaises(browser_mcp.BrowserMCPError) as fallo:
                browser_mcp._npx()

        self.assertIn("no existe", str(fallo.exception))

    def test_un_servidor_que_se_cierra_solo_se_reporta(self):
        proceso = unittest.mock.Mock()
        proceso.poll.return_value = 1
        proceso.returncode = 1

        with TemporaryDirectory() as perfil, \
             patch.object(browser_mcp, "escuchando", return_value=False), \
             patch.object(browser_mcp, "_npx", return_value="npx"), \
             patch.object(browser_mcp, "_lanzar", return_value=proceso), \
             patch.object(browser_mcp, "_perfil_por_defecto", return_value=Path(perfil)):
            with self.assertRaises(browser_mcp.BrowserMCPError) as fallo:
                browser_mcp.arrancar(puerto=8931, timeout=1.0)

        self.assertIn("cerró", str(fallo.exception))

    def test_un_puerto_libre_no_se_da_por_escuchando(self):
        with socket.socket() as libre:
            libre.bind(("127.0.0.1", 0))
            puerto = libre.getsockname()[1]

        self.assertFalse(browser_mcp.escuchando(puerto, timeout=0.2))

    def test_un_puerto_ocupado_se_detecta(self):
        with socket.socket() as ocupado:
            ocupado.bind(("127.0.0.1", 0))
            ocupado.listen(1)
            puerto = ocupado.getsockname()[1]

            self.assertTrue(browser_mcp.escuchando(puerto, timeout=1.0))


class CambiarDeNavegadorEntreArranques(unittest.TestCase):
    """El servidor sobrevive al agente, así que hay que saber a qué apunta.

    Es la avería más silenciosa de todas: cambiar `PLAYWRIGHT_MCP_MODE`, ver
    que el puerto contesta, darlo por bueno y seguir navegando en el navegador
    de antes. Nadie lo denuncia y el síntoma es «lo he cambiado y no hace nada».
    """

    def setUp(self):
        """El módulo recuerda qué servidor lanzó, y eso se pega entre pruebas.

        Un test que llega a `_lanzar` deja `_proceso` apuntando a su Mock, y el
        siguiente arranca creyendo que tiene un servidor propio en pie: toma la
        rama de «nuestro pero apuntando a otro sitio» en vez de la del heredado,
        y falla por un motivo que no tiene nada que ver con lo que probaba.
        """
        self.addCleanup(setattr, browser_mcp, "_proceso", None)
        self.addCleanup(setattr, browser_mcp, "_endpoint", "")
        self.addCleanup(setattr, browser_mcp, "_huella_actual", "")
        browser_mcp._proceso = None
        browser_mcp._endpoint = ""
        browser_mcp._huella_actual = ""

    def _perfil(self, home, endpoint, pid=4321):
        browser_mcp._escribir_marca(Path(home), endpoint, pid)
        return Path(home)

    def test_uno_heredado_del_mismo_navegador_se_reaprovecha(self):
        with TemporaryDirectory() as home:
            perfil = self._perfil(home, "http://127.0.0.1:9333")
            with patch.object(browser_mcp, "escuchando", return_value=True), \
                 patch.object(browser_mcp, "_lanzar") as lanzar:
                salida = browser_mcp.arrancar(
                    8931, perfil=perfil, cdp_endpoint="http://127.0.0.1:9333"
                )

        lanzar.assert_not_called()
        self.assertFalse(salida["arrancado_ahora"])
        self.assertEqual(salida["cdp_endpoint"], "http://127.0.0.1:9333")

    def test_uno_heredado_de_otro_navegador_se_reemplaza(self):
        """Sin esto se navega en el Chrome vacío justo tras pedir lo contrario."""
        with TemporaryDirectory() as home:
            perfil = self._perfil(home, "")  # el de antes iba en modo perfil
            proceso = unittest.mock.Mock()
            proceso.poll.return_value = None
            proceso.pid = 999

            with patch.object(browser_mcp, "escuchando", return_value=True), \
                 patch.object(browser_mcp, "_matar_pid", return_value=True) as matar, \
                 patch.object(browser_mcp, "_npx", return_value="npx"), \
                 patch.object(browser_mcp, "_lanzar", return_value=proceso) as lanzar:
                salida = browser_mcp.arrancar(
                    8931, perfil=perfil, cdp_endpoint="http://127.0.0.1:9333"
                )

        matar.assert_called_once_with(4321)
        lanzar.assert_called_once()
        self.assertEqual(salida["cdp_endpoint"], "http://127.0.0.1:9333")

    def test_uno_enganchado_a_un_navegador_que_ya_murio_se_reemplaza(self):
        """Cerrar el navegador no cierra el servidor MCP, y el puerto sigue
        contestando tan tranquilo. Medido en la máquina del usuario el
        22/08/2026: servidor en pie desde hacía dos horas, `--cdp-endpoint`
        apuntando a un 9333 que ya no escuchaba, y el modelo recibiendo sus
        `browser_*` para que fallaran todas.

        Comparar el endpoint no lo detecta —es literalmente el mismo—, así que
        lo que se compara es qué instancia hay detrás.
        """
        with TemporaryDirectory() as home:
            browser_mcp._escribir_marca(
                Path(home), "http://127.0.0.1:9333", 4321, "el-navegador-de-antes"
            )
            proceso = unittest.mock.Mock()
            proceso.poll.return_value = None
            proceso.pid = 999

            with patch.object(browser_mcp, "escuchando", return_value=True), \
                 patch.object(
                     browser_mcp, "_huella_navegador", return_value="el-nuevo"
                 ), \
                 patch.object(browser_mcp, "_matar_pid", return_value=True) as matar, \
                 patch.object(browser_mcp, "_npx", return_value="npx"), \
                 patch.object(browser_mcp, "_lanzar", return_value=proceso) as lanzar:
                browser_mcp.arrancar(
                    8931, perfil=Path(home), cdp_endpoint="http://127.0.0.1:9333"
                )

        matar.assert_called_once_with(4321)
        lanzar.assert_called_once()

    def test_el_mismo_navegador_de_siempre_no_se_reemplaza(self):
        """El caso normal es este, y relanzar aquí costaría un arranque de
        servidor en cada sesión."""
        with TemporaryDirectory() as home:
            browser_mcp._escribir_marca(
                Path(home), "http://127.0.0.1:9333", 4321, "el-de-siempre"
            )
            with patch.object(browser_mcp, "escuchando", return_value=True), \
                 patch.object(
                     browser_mcp, "_huella_navegador", return_value="el-de-siempre"
                 ), \
                 patch.object(browser_mcp, "_lanzar") as lanzar:
                salida = browser_mcp.arrancar(
                    8931, perfil=Path(home), cdp_endpoint="http://127.0.0.1:9333"
                )

        lanzar.assert_not_called()
        self.assertFalse(salida["arrancado_ahora"])

    def test_una_marca_de_antes_de_esto_se_respeta(self):
        """La marca escrita por una versión anterior no lleva huella, y no
        tenerla no es motivo para relanzar: sería un arranque de más para todo
        el que actualice, y por una sospecha sin fundamento."""
        with TemporaryDirectory() as home:
            perfil = self._perfil(home, "http://127.0.0.1:9333")
            with patch.object(browser_mcp, "escuchando", return_value=True), \
                 patch.object(browser_mcp, "_huella_navegador", return_value="otra"), \
                 patch.object(browser_mcp, "_lanzar") as lanzar:
                salida = browser_mcp.arrancar(
                    8931, perfil=perfil, cdp_endpoint="http://127.0.0.1:9333"
                )

        lanzar.assert_not_called()
        self.assertFalse(salida["arrancado_ahora"])

    def test_si_no_se_puede_cerrar_el_viejo_se_dice(self):
        with TemporaryDirectory() as home:
            perfil = self._perfil(home, "")
            with patch.object(browser_mcp, "escuchando", return_value=True), \
                 patch.object(browser_mcp, "_matar_pid", return_value=False), \
                 patch.object(browser_mcp, "_lanzar") as lanzar:
                with self.assertRaises(browser_mcp.BrowserMCPError) as fallo:
                    browser_mcp.arrancar(
                        8931, perfil=perfil, cdp_endpoint="http://127.0.0.1:9333"
                    )

        lanzar.assert_not_called()
        self.assertIn("ocupado", str(fallo.exception))

    def test_la_marca_queda_escrita_al_arrancar(self):
        """Es lo único que sobrevive al reinicio del agente."""
        with TemporaryDirectory() as home:
            proceso = unittest.mock.Mock()
            proceso.poll.return_value = None
            proceso.pid = 777
            escuchas = iter([False, True])

            with patch.object(
                browser_mcp, "escuchando", side_effect=lambda *a, **k: next(escuchas)
            ), patch.object(browser_mcp, "_npx", return_value="npx"), \
                 patch.object(browser_mcp, "_lanzar", return_value=proceso):
                browser_mcp.arrancar(
                    8931, perfil=Path(home), cdp_endpoint="http://127.0.0.1:9333"
                )

            marca = browser_mcp._leer_marca(Path(home))

        self.assertEqual(marca["endpoint"], "http://127.0.0.1:9333")
        self.assertEqual(marca["pid"], 777)

    def test_un_pid_reciclado_no_se_mata(self):
        """La marca puede llevar días en disco y el número ser ya de otra cosa."""
        with patch.object(browser_mcp, "_es_nuestro_servidor", return_value=False), \
             patch.object(browser_mcp, "_matar_arbol") as matar:
            self.assertFalse(browser_mcp._matar_pid(4321))

        matar.assert_not_called()

    def test_se_reconoce_por_la_orden_y_no_por_el_nombre(self):
        """El proceso que se lanza es un `cmd.exe`, y hay cientos."""
        with patch.object(
            browser_mcp, "_orden",
            return_value="cmd /c npx --yes @playwright/mcp@latest --port 8931",
        ):
            self.assertTrue(browser_mcp._es_nuestro_servidor(1))

        with patch.object(browser_mcp, "_orden", return_value="cmd /c otra cosa"):
            self.assertFalse(browser_mcp._es_nuestro_servidor(1))

    def test_se_cierra_el_arbol_entero_y_no_el_envoltorio(self):
        """Quien escucha el puerto es un nieto: cmd -> node -> cmd -> node.

        Cerrar solo el primero deja el puerto ocupado por un huérfano, y el
        servidor que se lanza después se muere al no poder quedárselo. Es lo
        que hacía que cambiar de modo no sirviera de nada.
        """
        proceso = unittest.mock.Mock()
        proceso.pid = 555

        with patch.object(browser_mcp, "_matar_arbol") as matar:
            browser_mcp._terminar(proceso)

        matar.assert_called_once_with(555)
        proceso.terminate.assert_not_called()

    def test_pararlo_borra_la_marca(self):
        """Si no, el arranque siguiente intenta cerrar un pid que ya no está."""
        with TemporaryDirectory() as home:
            browser_mcp._escribir_marca(Path(home), "http://127.0.0.1:9333", 1)
            with patch.object(browser_mcp, "escuchando", return_value=False):
                browser_mcp.parar(8931, perfil=Path(home))

            self.assertEqual(browser_mcp._leer_marca(Path(home)), {})


class ValidarLoQuePideElServidor(unittest.TestCase):
    """Los argumentos llegan por la red: no se pasan a `Popen` a ciegas."""

    def test_un_puerto_que_no_es_numero_se_rechaza(self):
        with self.assertRaises(capabilities.CapabilityError):
            capabilities._browser_mcp(None, {"accion": "arrancar", "puerto": "; rm -rf"})

    def test_un_puerto_fuera_de_rango_se_rechaza(self):
        with self.assertRaises(capabilities.CapabilityError):
            capabilities._browser_mcp(None, {"accion": "arrancar", "puerto": 99999})

    def test_una_accion_inventada_se_rechaza(self):
        with self.assertRaises(capabilities.CapabilityError):
            capabilities._browser_mcp(None, {"accion": "formatear"})

    def test_sin_accion_arranca(self):
        with patch.object(browser_mcp, "arrancar", return_value={"estado": "ok"}) as arrancar:
            capabilities._browser_mcp(None, {})

        arrancar.assert_called_once()

    def test_el_host_que_pide_el_servidor_llega_al_comando(self):
        with patch.object(browser_mcp, "arrancar", return_value={"estado": "ok"}) as arrancar:
            capabilities._browser_mcp(
                None, {"accion": "arrancar", "hosts": "host.docker.internal"}
            )

        self.assertEqual(
            arrancar.call_args.kwargs["hosts_permitidos"], "host.docker.internal"
        )

    def test_sin_bind_explicito_escucha_solo_en_localhost(self):
        with patch.object(browser_mcp, "arrancar", return_value={"estado": "ok"}) as arrancar:
            capabilities._browser_mcp(None, {"accion": "arrancar"})

        self.assertEqual(arrancar.call_args.kwargs["host"], "127.0.0.1")

    def test_el_bind_del_servidor_se_respeta(self):
        """Hace falta si el nodo no es la máquina donde corre el contenedor."""
        with patch.object(browser_mcp, "arrancar", return_value={"estado": "ok"}) as arrancar:
            capabilities._browser_mcp(None, {"accion": "arrancar", "bind": "0.0.0.0"})

        self.assertEqual(arrancar.call_args.kwargs["host"], "0.0.0.0")


class DeclararElNavegadorEnAgy(unittest.TestCase):
    def _config(self, home):
        return home / ".gemini" / "config" / "mcp_config.json"

    def test_con_url_se_declara_como_servidor_remoto(self):
        """`agy` acepta `command` o `serverUrl`; este corre en otra máquina."""
        with TemporaryDirectory() as home:
            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                antigravity_chat.escribir_configuracion_mcp(
                    "u-1", "http://host.docker.internal:8931/sse"
                )
            guardado = json.loads(self._config(Path(home)).read_text(encoding="utf-8"))

        navegador = guardado["mcpServers"][antigravity_chat.SERVIDOR_NAVEGADOR]
        self.assertEqual(navegador["serverUrl"], "http://host.docker.internal:8931/sse")
        # Y el puente de siempre sigue ahí.
        self.assertIn("vibi", guardado["mcpServers"])

    def test_sin_url_la_entrada_se_borra(self):
        """Apuntando a un puerto muerto, `agy` gasta el arranque en vano."""
        with TemporaryDirectory() as home:
            destino = self._config(Path(home))
            destino.parent.mkdir(parents=True)
            destino.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            antigravity_chat.SERVIDOR_NAVEGADOR: {
                                "serverUrl": "http://viejo:8931/sse"
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(antigravity_chat.Path, "home", return_value=Path(home)):
                antigravity_chat.escribir_configuracion_mcp("u-1")

            guardado = json.loads(destino.read_text(encoding="utf-8"))

        self.assertNotIn(antigravity_chat.SERVIDOR_NAVEGADOR, guardado["mcpServers"])

    def test_no_reescribe_si_nada_ha_cambiado(self):
        """Tocar el archivo por gusto no aporta y despista al mirar fechas."""
        with TemporaryDirectory() as home:
            url = "http://host.docker.internal:8931/sse"
            with (
                patch.object(
                    antigravity_chat.Path, "home", return_value=Path(home)
                ),
                patch(
                    "app.auth.create_access_token",
                    side_effect=("token-anterior", "token-nuevo"),
                ),
                patch(
                    "app.auth.decode_access_token",
                    return_value={"sub": "u-1", "exp": 10**12},
                ),
            ):
                antigravity_chat.escribir_configuracion_mcp("u-1", url)

                with patch.object(
                    antigravity_chat.Path, "write_text", autospec=True
                ) as escribir:
                    antigravity_chat.escribir_configuracion_mcp("u-1", url)

        escribir.assert_not_called()

    def test_renueva_un_token_sin_vida_para_otra_sesion_completa(self):
        with TemporaryDirectory() as home:
            url = "http://host.docker.internal:8931/sse"
            with (
                patch.object(
                    antigravity_chat.Path, "home", return_value=Path(home)
                ),
                patch(
                    "app.auth.create_access_token",
                    side_effect=("token-anterior", "token-nuevo"),
                ),
                patch(
                    "app.auth.decode_access_token",
                    return_value={"sub": "u-1", "exp": 0},
                ),
            ):
                antigravity_chat.escribir_configuracion_mcp("u-1", url)

                with patch.object(
                    antigravity_chat.Path, "write_text", autospec=True
                ) as escribir:
                    antigravity_chat.escribir_configuracion_mcp("u-1", url)

        escribir.assert_called_once()
        self.assertIn("token-nuevo", escribir.call_args.args[1])


class PrecalentarEsperaALosNodos(unittest.IsolatedAsyncioTestCase):
    """Lo que se decide al montar la sesión dura lo que dure el proceso.

    Si al arrancar el servidor el ordenador del usuario todavía no ha
    reconectado, esa sesión se queda sin navegador hasta que caduque.
    """

    async def test_espera_a_que_haya_alguno_conectado(self):
        from app import main

        llamadas = {"n": 0}

        def conectados():
            llamadas["n"] += 1
            return ("nodo-1",) if llamadas["n"] > 2 else ()

        with patch.object(main.nodes.manager, "online_ids", side_effect=conectados), \
             patch.object(main, "SONDEO_NODOS", 0.01):
            self.assertTrue(await main._esperar_algun_nodo())

        self.assertGreater(llamadas["n"], 1)

    async def test_sin_nodos_se_rinde_y_precalienta_igual(self):
        """Un usuario sin dispositivos tiene que poder conversar igual."""
        from app import main

        with patch.object(main.nodes.manager, "online_ids", return_value=()), \
             patch.object(main, "ESPERA_NODOS_SEGUNDOS", 0.05), \
             patch.object(main, "SONDEO_NODOS", 0.01):
            self.assertFalse(await main._esperar_algun_nodo())


class LasReglasNoPrometenLoQueNoHay(unittest.TestCase):
    """Lo que se comprueba es la herramienta, no la palabra.

    Estos dos tests miraban si aparecía «playwright» en minúscula, y el prompt
    nunca la ha escrito así: el de arriba llevaba roto desde que se escribió y
    el de abajo pasaba por el mismo accidente, sin comprobar nada. Lo que de
    verdad importa es si el modelo se va a creer que tiene el navegador, y eso
    se lee en si se le nombran las `browser_*`.
    """

    def _reglas(self, **como) -> str:
        with TemporaryDirectory() as workspace:
            antigravity_chat.escribir_reglas(workspace, "Rubén", **como)
            return (Path(workspace) / antigravity_chat.ARCHIVO_REGLAS).read_text(
                encoding="utf-8"
            )

    def test_con_navegador_se_le_cuenta(self):
        reglas = self._reglas(navegador=True)

        self.assertIn("browser_navigate", reglas)
        self.assertIn("Rubén", reglas)

    def test_sin_navegador_se_le_dice_que_no_lo_tiene(self):
        """No basta con callarse: sin decir nada, el modelo que tiene terminal
        abre la web con `Start-Process` y asegura haberla mirado. Se le nombra
        justo para negarlo."""
        reglas = self._reglas(navegador=False)

        self.assertIn("NO tienes", reglas)
        self.assertNotIn("browser_navigate", reglas)

    def test_con_navegador_no_se_le_promete_estar_dentro_de_todo(self):
        """El perfil es de Vibi y persistente: en unos sitios habrá sesión y en
        otros no. Prometer que las hereda del navegador del usuario —lo que
        decía mientras se compartía perfil— acaba en un acceso inventado."""
        reglas = self._reglas(navegador=True)

        self.assertIn("perfil propio", reglas)
        self.assertNotIn("donde él está dentro, tú estás dentro", reglas)

    def test_chrome_y_google_son_el_disparador_de_playwright(self):
        """Petición suya: el navegador propio se usa cuando dice «chrome» o
        «google» —donde viven ahora sus sesiones—, y por defecto abre en Zen.
        Las dos palabras tienen que estar escritas como disparador, o el modelo
        no sabe cuándo cambiar de un navegador al otro."""
        reglas = self._reglas(navegador=True).lower()

        self.assertIn("chrome", reglas)
        self.assertIn("google", reglas)

    def test_abrir_a_secas_va_a_zen_y_no_al_navegador_propio(self):
        """«ábreme/ponme» sin más es para que lo mire él, y va al de siempre.
        Si esto se pierde, el modelo abre todo en Chrome y {nombre} no ve nada
        en su navegador de diario."""
        reglas = self._reglas(navegador=True)

        self.assertIn("devices_open_url", reglas)
        self.assertIn("Zen", reglas)

    def test_entrar_a_leer_o_rellenar_sigue_siendo_del_navegador_propio(self):
        """La excepción técnica que se decidió conservar: aunque no diga
        «chrome», si hay que sacar un dato de dentro o rellenar algo es Chrome,
        porque Zen no se puede pilotar. Quitarla dejaría a Vibi sin poder
        trabajar dentro de una web que no nombre el navegador."""
        reglas = self._reglas(navegador=True).lower()

        self.assertIn("rellenar", reglas)
        self.assertIn("browser_", reglas)


class EncenderElNavegadorAntesDeArrancarAgy(unittest.IsolatedAsyncioTestCase):
    USUARIO = {"id": "u-1", "nombre": "Rubén"}

    async def test_devuelve_la_url_que_ve_el_contenedor(self):
        from app import tools

        with patch.object(tools, "resolve_device", return_value={"nombre": "PC"}), \
             patch.object(
                 nodes, "dispatch",
                 unittest.mock.AsyncMock(
                     return_value={"estado": "ok", "resultado": {"puerto": 8931}}
                 ),
             ) as dispatch:
            url = await antigravity_chat.asegurar_playwright(self.USUARIO)

        self.assertIn("8931", url)
        self.assertIn(antigravity_chat.settings.playwright_mcp_host, url)
        # No se encola: un navegador que se abre mañana no le sirve a nadie.
        self.assertFalse(dispatch.await_args.kwargs["queue_if_offline"])
        # Y el nodo tiene que saber con qué nombre le van a llamar.
        argumentos = dispatch.await_args.args[3]
        self.assertEqual(
            argumentos["hosts"], antigravity_chat.settings.playwright_mcp_host
        )

    async def test_un_enganche_fallido_no_deja_a_agy_sin_navegador(self):
        """El servidor sigue en pie y el modelo puede intentarlo él. Quitarle la
        URL por esto le dejaría sin navegar por algo que era recuperable."""
        from app import tools

        with patch.object(tools, "resolve_device", return_value={"nombre": "PC"}), \
             patch.object(
                 nodes, "dispatch",
                 unittest.mock.AsyncMock(
                     return_value={
                         "estado": "ok",
                         "resultado": {
                             "puerto": 8931,
                             "enganche": {
                                 "enganchado": False,
                                 "ms": 10_000,
                                 "error": "TimeoutError: async initializeServer",
                             },
                         },
                     }
                 ),
             ):
            with self.assertLogs(antigravity_chat.log, level="WARNING") as registro:
                url = await antigravity_chat.asegurar_playwright(self.USUARIO)

        self.assertIn("8931", url)
        self.assertIn("engancharse", "\n".join(registro.output))

    async def test_sin_dispositivo_conectado_no_es_un_error(self):
        from app import tools

        with patch.object(
            tools, "resolve_device", side_effect=tools.ToolNotFound("no hay")
        ):
            url = await antigravity_chat.asegurar_playwright(self.USUARIO)

        self.assertEqual(url, "")

    async def test_un_nodo_que_falla_deja_la_conversacion_en_pie(self):
        from app import tools

        with patch.object(tools, "resolve_device", return_value={"nombre": "PC"}), \
             patch.object(
                 nodes, "dispatch",
                 unittest.mock.AsyncMock(side_effect=nodes.NodeOffline("apagado")),
             ):
            url = await antigravity_chat.asegurar_playwright(self.USUARIO)

        self.assertEqual(url, "")

    async def test_apagado_por_configuracion_no_pregunta_a_nadie(self):
        from app import tools

        with patch.object(antigravity_chat.settings, "playwright_mcp_enabled", False), \
             patch.object(tools, "resolve_device") as resolver:
            url = await antigravity_chat.asegurar_playwright(self.USUARIO)

        resolver.assert_not_called()
        self.assertEqual(url, "")


if __name__ == "__main__":
    unittest.main()

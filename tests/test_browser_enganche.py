"""El enganche: dejar a Playwright ya conectado, y no a punto de conectarse.

Lo que se arregla aquí es un problema de *momento*, no de método. El pre-vuelo
de pestañas ya sabía despertarlas, pero corría al abrir la sesión de `agy`,
mientras que Playwright no se engancha al navegador hasta la primera llamada a
una herramienta, que puede ser una hora después. En ese hueco Opera descarta
pestañas —medido el 16/08/2026: 6 de 12 en 79 minutos— y entonces
`connectOverCDP` se queda esperando a que se inicialicen todas, falla a los 30
s, y como una conexión fallida no se guarda, **cada** llamada del modelo vuelve
a pagar los 30 s.

Medido contra el servidor real: `browser_snapshot` costaba 30 031 ms y devolvía
`TimeoutError` con las pestañas dormidas, y 633 ms con ellas despiertas.
"""
import json
import unittest
from unittest.mock import patch

from agent.vibi_node import browser_enganche, capabilities


class UnaRespuesta:
    def __init__(self, cuerpo: str = "", estado: int = 200, sesion: str = ""):
        self._cuerpo, self.status, self._sesion = cuerpo, estado, sesion

    def read(self) -> bytes:
        return self._cuerpo.encode("utf-8")

    def getheader(self, nombre: str, por_defecto=None):
        if nombre.lower() == "mcp-session-id" and self._sesion:
            return self._sesion
        return por_defecto


class UnServidorFalso:
    """Apunta lo que se le pide y contesta lo que le hayan dicho."""

    def __init__(self, *respuestas: UnaRespuesta):
        self.respuestas = list(respuestas)
        self.peticiones: list[dict] = []

    def __call__(self, *_args, **_kwargs):
        return self

    def request(self, metodo, ruta, cuerpo=None, cabeceras=None):
        self.peticiones.append(
            {
                "metodo": metodo,
                "ruta": ruta,
                "cuerpo": json.loads(cuerpo) if cuerpo else None,
                "cabeceras": cabeceras or {},
            }
        )

    def getresponse(self):
        return self.respuestas.pop(0) if self.respuestas else UnaRespuesta()

    def close(self):
        pass


def _sse(payload: dict) -> str:
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def _resultado(texto: str) -> str:
    return _sse({"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": texto}]}})


def _servidor(texto_final: str, estado: int = 200) -> UnServidorFalso:
    return UnServidorFalso(
        UnaRespuesta(_sse({"jsonrpc": "2.0", "id": 1, "result": {}}), sesion="s-1"),
        UnaRespuesta("", 202),                       # notifications/initialized
        UnaRespuesta(_resultado(texto_final), estado),
        UnaRespuesta("", 200),                       # el DELETE de la sesión
    )


class HablarleAlServidorComoLeHablaElContenedor(unittest.TestCase):
    def test_va_con_el_host_declarado_y_no_con_localhost(self):
        """Comprobado contra el servidor real: por `127.0.0.1` devuelve 403.

        `--allowed-hosts` no añade nombres a los de por defecto, los sustituye,
        así que el agente tiene que llamarse a sí mismo con el mismo nombre que
        usa el contenedor. Sin esto el enganche fallaría siempre, y en silencio.
        """
        servidor = _servidor("### Open tabs\n- 0: (current) [x](https://x.test)")

        with patch.object(browser_enganche, "_conexion", servidor):
            browser_enganche.enganchar(8931, "host.docker.internal")

        for peticion in servidor.peticiones:
            self.assertEqual(peticion["cabeceras"]["Host"], "host.docker.internal:8931")

    def test_sin_hosts_declarados_no_se_inventa_ninguno(self):
        """El valor por defecto de Playwright ya cubre trabajar en local."""
        servidor = _servidor("### Open tabs")

        with patch.object(browser_enganche, "_conexion", servidor):
            browser_enganche.enganchar(8931, "")

        self.assertNotIn("Host", servidor.peticiones[0]["cabeceras"])

    def test_se_pide_algo_que_obliga_a_mirar_el_navegador(self):
        """Un `tools/list` lo contesta el servidor solo, sin tocar el navegador,
        y entonces no forzaría la conexión, que es justo lo que se busca."""
        servidor = _servidor("### Open tabs")

        with patch.object(browser_enganche, "_conexion", servidor):
            browser_enganche.enganchar(8931, "host.docker.internal")

        llamada = servidor.peticiones[2]["cuerpo"]
        self.assertEqual(llamada["method"], "tools/call")
        self.assertEqual(llamada["params"]["name"], browser_enganche.HERRAMIENTA)

    def test_la_sesion_se_cierra_al_terminar(self):
        """Se abre uña sesión MCP solo para esto; dejarla abierta las acumula."""
        servidor = _servidor("### Open tabs")

        with patch.object(browser_enganche, "_conexion", servidor):
            browser_enganche.enganchar(8931, "host.docker.internal")

        self.assertEqual(servidor.peticiones[-1]["metodo"], "DELETE")

    def test_no_se_lee_nada_del_navegador(self):
        """Lo que devuelva la herramienta es basura para nosotros: puede traer
        los títulos de las pestañas del usuario, y esto solo pregunta si el
        navegador contesta. Lo que se devuelve es un sí o un no."""
        servidor = _servidor("### Open tabs\n- 0: [Banco](https://banco.test/cuenta)")

        with patch.object(browser_enganche, "_conexion", servidor):
            salida = browser_enganche.enganchar(8931, "host.docker.internal")

        self.assertNotIn("banco.test", json.dumps(salida))


class DistinguirElEngancheBuenoDelMalo(unittest.TestCase):
    def test_una_respuesta_normal_cuenta_como_enganchado(self):
        servidor = _servidor("### Open tabs\n- 0: (current) [x](https://x.test)")

        with patch.object(browser_enganche, "_conexion", servidor):
            salida = browser_enganche.enganchar(8931, "host.docker.internal")

        self.assertTrue(salida["enganchado"])

    def test_el_timeout_del_cdp_no_cuenta_como_enganchado(self):
        """Es el fallo de verdad, y llega con un 200 y un texto de error dentro:
        el servidor MCP contesta bien a una llamada que salió mal."""
        servidor = _servidor(
            "### Error\nTimeoutError: async initializeServer: Timeout 30000ms exceeded."
        )

        with patch.object(browser_enganche, "_conexion", servidor):
            salida = browser_enganche.enganchar(8931, "host.docker.internal")

        self.assertFalse(salida["enganchado"])
        self.assertIn("Timeout", salida["error"])

    def test_un_403_se_cuenta_como_fallo_y_no_revienta(self):
        servidor = UnServidorFalso(UnaRespuesta("", 403))

        with patch.object(browser_enganche, "_conexion", servidor):
            salida = browser_enganche.enganchar(8931, "host.docker.internal")

        self.assertFalse(salida["enganchado"])
        self.assertIn("403", salida["error"])

    def test_un_servidor_que_no_contesta_no_revienta(self):
        """Al nodo le llega esto en mitad de abrir una sesión: si aquí sube una
        excepción, se queda sin navegador por algo que era opcional."""
        def cae(*_a, **_k):
            raise OSError("conexión rechazada")

        with patch.object(browser_enganche, "_conexion", cae):
            salida = browser_enganche.enganchar(8931, "host.docker.internal")

        self.assertFalse(salida["enganchado"])
        self.assertTrue(salida["error"])

    def test_se_dice_cuánto_ha_costado(self):
        """Es el número que hacía falta para ver el problema desde los logs."""
        servidor = _servidor("### Open tabs")

        with patch.object(browser_enganche, "_conexion", servidor):
            salida = browser_enganche.enganchar(8931, "host.docker.internal")

        self.assertIsInstance(salida["ms"], int)


class NoEsperarLosTreintaSegundos(unittest.TestCase):
    def test_el_margen_es_mas_corto_que_el_del_cdp(self):
        """Si el enganche se rinde antes que Playwright, lo da por fallido
        mientras la conexión seguía haciéndose, y el reintento la duplica."""
        from agent.vibi_node import browser_mcp

        self.assertGreater(browser_enganche.TIMEOUT * 1000, browser_mcp.CDP_TIMEOUT_MS)

    def test_el_comando_le_acota_la_espera_a_playwright(self):
        from agent.vibi_node import browser_mcp

        with patch.object(browser_mcp, "_npx", return_value="npx"):
            argv = browser_mcp.comando(
                8931, "chrome", __import__("pathlib").Path("."), "127.0.0.1",
                cdp_endpoint="http://127.0.0.1:9333",
            )

        self.assertEqual(
            argv[argv.index("--cdp-timeout") + 1], str(browser_mcp.CDP_TIMEOUT_MS)
        )

    def test_la_version_del_servidor_va_fijada(self):
        """No por velocidad —medido: `@latest` 1249 ms y la fija 1295 ms, o sea
        igual—, sino porque dentro van los nombres de las herramientas y sus
        argumentos. Con `@latest` una publicación cualquiera deja al modelo
        llamando a algo que ya no existe, sin haber tocado nada aquí."""
        from agent.vibi_node import browser_mcp

        self.assertNotIn("@latest", browser_mcp.PAQUETE)
        self.assertTrue(browser_mcp.PAQUETE.startswith(browser_mcp.NOMBRE_PAQUETE + "@"))

    def test_un_servidor_de_otra_version_se_sigue_reconociendo(self):
        """Al subir de versión hay que poder cerrar el que dejó la anterior."""
        from agent.vibi_node import browser_mcp

        with patch.object(
            browser_mcp, "_orden",
            return_value="cmd /c npx --yes @playwright/mcp@0.0.70 --port 8931",
        ):
            self.assertTrue(browser_mcp._es_nuestro_servidor(1))

    def test_en_modo_perfil_no_se_acota(self):
        """Ahí el navegador lo lanza Playwright y no hay pestañas de nadie que
        puedan estar descartadas: el margen de siempre vale."""
        from agent.vibi_node import browser_mcp

        with patch.object(browser_mcp, "_npx", return_value="npx"):
            argv = browser_mcp.comando(
                8931, "chrome", __import__("pathlib").Path("."), "127.0.0.1"
            )

        self.assertNotIn("--cdp-timeout", argv)


class DespertarSoloCuandoHaceFalta(unittest.TestCase):
    """Despertar una pestaña es recargarla, y eso no es gratis para el usuario.

    Por eso el pre-vuelo no se hace «por si acaso» antes de cada arranque: se
    pregunta primero si el navegador contesta, que cuesta menos de un segundo,
    y solo si no contesta se le tocan las pestañas.
    """

    ARGUMENTOS = {
        "accion": "arrancar",
        "modo": "cdp",
        "cdp_puerto": 9333,
        "navegador_ruta": "opera.exe",
        "hosts": "host.docker.internal",
    }

    def _parchear(self, enganches):
        from agent.vibi_node import capabilities

        return (
            patch.object(
                capabilities.navegador_real, "asegurar",
                return_value={"endpoint": "http://127.0.0.1:9333"},
            ),
            patch.object(
                capabilities.browser_mcp, "arrancar",
                return_value={"estado": "ok", "puerto": 8931},
            ),
            patch.object(
                capabilities.browser_enganche, "enganchar", side_effect=enganches
            ),
            patch.object(
                capabilities.navegador_real, "despertar_pestanas",
                return_value={"revisadas": 12, "despertadas": 6, "tercas": 0},
            ),
        )

    def test_si_engancha_a_la_primera_no_se_toca_ninguna_pestana(self):
        from agent.vibi_node import capabilities

        asegurar, arrancar, enganchar, despertar = self._parchear(
            [{"enganchado": True, "ms": 900, "error": ""}]
        )
        with asegurar, arrancar, enganchar, despertar as despertadas:
            salida = capabilities._browser_mcp(None, dict(self.ARGUMENTOS))

        despertadas.assert_not_called()
        self.assertTrue(salida["enganche"]["enganchado"])

    def test_si_falla_se_despiertan_las_pestanas_y_se_reintenta(self):
        """Este es el arreglo entero: el fallo de la primera es la señal de que
        hay una pestaña descartada, y ahí sí toca recargarla."""
        from agent.vibi_node import capabilities

        asegurar, arrancar, enganchar, despertar = self._parchear(
            [
                {"enganchado": False, "ms": 10_000, "error": "TimeoutError"},
                {"enganchado": True, "ms": 800, "error": ""},
            ]
        )
        with asegurar, arrancar, enganchar as enganches, despertar as despertadas:
            salida = capabilities._browser_mcp(None, dict(self.ARGUMENTOS))

        despertadas.assert_called_once()
        self.assertEqual(despertadas.call_args.args[0], 9333)
        # Y con presupuesto: sin él, sondear y recargar doce pestañas se comía
        # los 45 s que el servidor espera por la orden.
        self.assertGreater(despertadas.call_args.args[1], 0)
        self.assertLess(
            despertadas.call_args.args[1], capabilities.PRESUPUESTO_ENGANCHE
        )
        self.assertEqual(enganches.call_count, 2)
        self.assertTrue(salida["enganche"]["enganchado"])
        self.assertEqual(salida["enganche"]["pestanas"]["despertadas"], 6)

    def test_no_se_reintenta_mas_de_una_vez(self):
        """Si tras despertarlas sigue sin conectar, el problema es otro y
        seguir intentándolo solo gasta el tiempo del usuario."""
        from agent.vibi_node import capabilities

        fallo = {"enganchado": False, "ms": 10_000, "error": "TimeoutError"}
        asegurar, arrancar, enganchar, despertar = self._parchear([fallo, fallo])
        with asegurar, arrancar, enganchar as enganches, despertar:
            salida = capabilities._browser_mcp(None, dict(self.ARGUMENTOS))

        self.assertEqual(enganches.call_count, 2)
        self.assertFalse(salida["enganche"]["enganchado"])

    def test_el_arranque_entero_cabe_en_lo_que_espera_el_servidor(self):
        """Pasó de verdad el 16/08/2026: el camino de recuperación —rendirse,
        sondear, recargar, reintentar— se pasaba de los 45 s del dispatch, y el
        usuario se quedaba sin navegador por culpa de lo que iba a arreglárselo.
        """
        # Ahora el techo lo pone el presupuesto y no la suma de las partes: los
        # dos intentos y el pre-vuelo van todos contra el mismo reloj. Lo que
        # queda hasta 45 es para abrir el navegador, que va antes.
        self.assertLessEqual(capabilities.PRESUPUESTO_ENGANCHE, 25.0)

    def test_el_enganche_se_acota_a_si_mismo_y_no_por_peticion(self):
        """Son cuatro viajes. Con un margen por viaje, el peor caso era cuatro
        veces el margen y se salía de los 45 s del dispatch."""
        lentas: list[float] = []

        class Lenta(UnServidorFalso):
            def __call__(self, _puerto, timeout):
                lentas.append(timeout)
                return self

        servidor = Lenta(
            UnaRespuesta(_sse({"jsonrpc": "2.0", "id": 1, "result": {}}), sesion="s-1"),
            UnaRespuesta("", 202),
            UnaRespuesta(_resultado("### Open tabs"), 200),
            UnaRespuesta("", 200),
        )
        with patch.object(browser_enganche, "_conexion", servidor):
            browser_enganche.enganchar(8931, "host.docker.internal", timeout=6.0)

        self.assertGreater(len(lentas), 1)
        # Cada petición pide menos que la anterior: van contra el mismo reloj.
        self.assertLessEqual(lentas[-1], lentas[0])
        self.assertLessEqual(max(lentas), 6.0)

    def test_sin_tiempo_no_se_recarga_nada(self):
        """Despertar sin poder reintentar después le recarga las pestañas al
        usuario a cambio de nada."""
        fallo = {"enganchado": False, "ms": 1, "error": "TimeoutError"}
        with patch.object(
            capabilities.browser_enganche, "enganchar", return_value=fallo
        ), patch.object(
            capabilities.navegador_real, "despertar_pestanas"
        ) as despertadas:
            salida = capabilities._asegurar_enganche(
                8931, "host.docker.internal", 9333, presupuesto=0.0
            )

        despertadas.assert_not_called()
        self.assertTrue(salida["sin_tiempo"])

    def test_un_enganche_fallido_no_tumba_el_arranque(self):
        """El servidor está en pie igual, y el modelo puede intentarlo él. Que
        esto falle no es razón para dejar la sesión sin navegador."""
        from agent.vibi_node import capabilities

        fallo = {"enganchado": False, "ms": 10_000, "error": "TimeoutError"}
        asegurar, arrancar, enganchar, despertar = self._parchear([fallo, fallo])
        with asegurar, arrancar, enganchar, despertar:
            salida = capabilities._browser_mcp(None, dict(self.ARGUMENTOS))

        self.assertEqual(salida["estado"], "ok")

    def test_en_modo_perfil_no_se_engancha(self):
        """El navegador es de Playwright y lo abre él cuando le hace falta: no
        hay pestañas del usuario que puedan estar descartadas."""
        from agent.vibi_node import capabilities

        with patch.object(
            capabilities.browser_mcp, "arrancar",
            return_value={"estado": "ok", "puerto": 8931},
        ), patch.object(capabilities.browser_enganche, "enganchar") as enganchar:
            capabilities._browser_mcp(None, {"accion": "arrancar", "modo": "perfil"})

        enganchar.assert_not_called()

    def test_el_nombre_declarado_llega_al_enganche(self):
        """Sin él se come un 403 contra su propio servidor."""
        from agent.vibi_node import capabilities

        asegurar, arrancar, enganchar, despertar = self._parchear(
            [{"enganchado": True, "ms": 900, "error": ""}]
        )
        with asegurar, arrancar, enganchar as enganches, despertar:
            capabilities._browser_mcp(None, dict(self.ARGUMENTOS))

        self.assertEqual(enganches.call_args.args[1], "host.docker.internal")


if __name__ == "__main__":
    unittest.main()

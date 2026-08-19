"""Lo que el instalador cambia en la máquina.

El foco está en no destruir nada. Quien reinstala casi siempre ya tenía un
`.env` con sus claves dentro, y un instalador que lo sobrescribe le borra la
cuenta de Groq, el bot de Telegram y —peor— el `JWT_SECRET` con el que están
firmadas las sesiones abiertas.
"""
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from installer import acciones


class ElEnvSeCompletaSinPisarLoQueYaHabia(unittest.TestCase):
    def test_en_una_maquina_limpia_lo_escribe_entero(self):
        contenido = acciones.contenido_env({}, {"modelo": "gemini-3.6-flash-medium"})

        self.assertIn("ANTIGRAVITY_MODEL=gemini-3.6-flash-medium", contenido)
        self.assertIn("JWT_SECRET=", contenido)

    def test_inventa_un_jwt_secret_y_no_lo_repite_entre_instalaciones(self):
        """Un secreto por defecto compartido deja las sesiones falsificables."""
        uno = acciones.valor_de(acciones.contenido_env({}, {}), "JWT_SECRET")
        otro = acciones.valor_de(acciones.contenido_env({}, {}), "JWT_SECRET")

        self.assertTrue(uno)
        self.assertNotEqual(uno, otro)
        self.assertGreaterEqual(len(uno), 32)

    def test_respeta_el_jwt_secret_que_ya_estuviera(self):
        """Cambiarlo cierra la sesión de todos los dispositivos ya emparejados."""
        previo = {"JWT_SECRET": "el-de-siempre"}

        contenido = acciones.contenido_env(previo, {})

        self.assertEqual(acciones.valor_de(contenido, "JWT_SECRET"), "el-de-siempre")

    def test_conserva_las_claves_que_el_instalador_no_pregunta(self):
        previo = {
            "GROQ_API_KEY": "gsk-lo-mio",
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "PLAYWRIGHT_MCP_BROWSER_PATH": r"C:\Opera\opera.exe",
        }

        contenido = acciones.contenido_env(previo, {})

        for clave, valor in previo.items():
            self.assertEqual(acciones.valor_de(contenido, clave), valor)

    def test_lo_que_el_usuario_elige_gana_a_lo_que_habia(self):
        previo = {"ANTIGRAVITY_MODEL": "gemini-3.6-flash-low"}

        contenido = acciones.contenido_env(previo, {"modelo": "gemini-3.6-flash-high"})

        self.assertEqual(
            acciones.valor_de(contenido, "ANTIGRAVITY_MODEL"), "gemini-3.6-flash-high"
        )

    def test_las_capacidades_apagadas_quedan_apagadas_en_el_env(self):
        contenido = acciones.contenido_env({}, {"capacidades": {"navegador": False}})

        self.assertEqual(acciones.valor_de(contenido, "PLAYWRIGHT_MCP_ENABLED"), "false")

    def test_leer_un_env_existente_no_se_traga_los_comentarios(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / ".env"
            ruta.write_text(
                "# un comentario\nGROQ_API_KEY=abc\n\n  # otro\nTTS_VOICE=es-ES\n",
                encoding="utf-8",
            )

            leido = acciones.leer_env(ruta)

        self.assertEqual(leido, {"GROQ_API_KEY": "abc", "TTS_VOICE": "es-ES"})

    def test_un_valor_con_igual_dentro_se_lee_entero(self):
        """Las claves en base64 acaban en `=` y se partían por la mitad."""
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / ".env"
            ruta.write_text("JWT_SECRET=abc==\n", encoding="utf-8")

            self.assertEqual(acciones.leer_env(ruta)["JWT_SECRET"], "abc==")


class ElEnvGeneradoTieneQueValerleAlCore(unittest.TestCase):
    """Toda clave que escriba el instalador la tiene que aceptar `Settings`.

    Es la prueba que faltaba y que costó cara: el instalador escribía
    `CHAT_PROVIDER=antigravity` dando por hecho que era un ajuste del `.env`, y
    no lo es —el motor se guarda por usuario en la base de datos—. `Settings`
    prohíbe los campos que no conoce, así que esa línea no rompía el instalador:
    **rompía el arranque del core entero**, y con un error de pydantic que no
    menciona ni al instalador ni al `.env`.

    Comprobarlo clave por clave no serviría de nada; lo que hace falta es
    contrastar contra la configuración de verdad, para que cualquier ajuste
    nuevo que alguien añada aquí quede cubierto solo.
    """

    def test_ninguna_clave_es_rechazada_por_la_configuracion(self):
        from app.config import Settings

        contenido = acciones.contenido_env(
            {},
            {
                "modelo": "gemini-3.6-flash-medium",
                "effort": "medium",
                "capacidades": {"navegador": False, "terminal": True},
            },
        )
        valores = {
            linea.split("=", 1)[0]: linea.split("=", 1)[1]
            for linea in contenido.splitlines()
            if linea.strip() and not linea.startswith("#")
        }

        # `_env_file=None` para no mezclar el `.env` real de la máquina: lo que
        # se valida es lo que genera el instalador, no lo que ya hubiera.
        Settings(_env_file=None, **{k.lower(): v for k, v in valores.items()})

    def test_el_motor_no_se_guarda_en_el_env(self):
        """Vive en `user_ai_settings`, y ponerlo aquí tumba el arranque."""
        contenido = acciones.contenido_env({}, {"motor": "antigravity"})

        self.assertNotIn("CHAT_PROVIDER", contenido)


class DejarlaFuncionandoYNoDarUnComando(unittest.TestCase):
    """Un instalador termina con el programa funcionando, no con deberes.

    La primera versión acababa enseñando la ruta de un `.cmd` y una URL, y
    dejaba al usuario mirando una pantalla que decía «Vibi está despierta»
    mientras no había absolutamente nada corriendo. Arrancar es parte de
    instalar.
    """

    def test_espera_a_que_conteste_de_verdad(self):
        """Arrancar el proceso no es que esté lista: el core tarda unos
        segundos en abrir el puerto, y decir «ya está» antes de eso manda al
        usuario a una página que no carga."""
        respuestas = iter([ConnectionRefusedError(), ConnectionRefusedError(), 401])

        def sondear(_url):
            siguiente = next(respuestas)
            if isinstance(siguiente, Exception):
                raise siguiente
            return siguiente

        self.assertTrue(
            acciones.esperar_a_vibi("http://127.0.0.1:8000", 5, sondear, pausa=0)
        )

    def test_un_401_cuenta_como_viva(self):
        """Sin credenciales contesta 401, y eso ya prueba que está sirviendo."""
        self.assertTrue(
            acciones.esperar_a_vibi("http://x", 2, lambda _: 401, pausa=0)
        )

    def test_si_no_levanta_en_su_tiempo_no_miente(self):
        def nunca(_url):
            raise ConnectionRefusedError()

        self.assertFalse(acciones.esperar_a_vibi("http://x", 2, nunca, pausa=0))


class VibiSeAbreComoAplicacion(unittest.TestCase):
    """Una aplicación no abre el navegador. Nunca.

    La primera versión terminaba con un botón que lanzaba el navegador del
    sistema en `127.0.0.1:8000`, y eso no es una app: es un servidor con una
    pestaña delante. Lo que se abre es la ventana de Vibi.
    """

    def test_la_busca_donde_la_deja_su_instalador(self):
        with TemporaryDirectory() as local:
            carpeta = Path(local) / "Vibi"
            carpeta.mkdir()
            app = carpeta / "vibi-companion.exe"
            app.write_text("", encoding="utf-8")

            with patch.dict("os.environ", {"LOCALAPPDATA": local}), patch(
                "sys.platform", "win32"
            ):
                self.assertEqual(Path(acciones.donde_esta_la_app()), app)

    def test_si_no_esta_instalada_lo_dice_en_vez_de_abrir_el_navegador(self):
        with TemporaryDirectory() as local:
            with patch.dict("os.environ", {"LOCALAPPDATA": local}), patch(
                "sys.platform", "win32"
            ):
                self.assertEqual(acciones.donde_esta_la_app(), "")


class ElArranqueDependeDelSistema(unittest.TestCase):
    def test_cada_sistema_recibe_el_suyo(self):
        self.assertTrue(acciones.guion_de_arranque("windows", Path("/x")).endswith(".cmd"))
        for so in ("macos", "linux"):
            self.assertTrue(acciones.guion_de_arranque(so, Path("/x")).endswith(".sh"))

    def test_el_de_unix_es_ejecutable_y_arranca_los_dos_procesos(self):
        with TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            escrito = acciones.escribir_arranque("linux", raiz)

            contenido = Path(escrito).read_text(encoding="utf-8")

        self.assertIn("uvicorn", contenido)
        self.assertIn("vibi_node", contenido)


if __name__ == "__main__":
    unittest.main()

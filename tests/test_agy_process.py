"""El proceso `agy`: encontrar su puerto y teclearle el turno."""
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.executors import agy_process


class PuertoDelLanguageServer(unittest.TestCase):
    """El puerto es aleatorio en cada arranque y solo se sabe por el log."""

    def test_lo_saca_de_la_linea_del_log(self):
        log = (
            "I0806 server.go:561] Language server listening on random port at"
            " 61320 for HTTPS (gRPC)\n"
            "I0806 server.go:569] Language server listening on random port at"
            " 61321 for HTTP\n"
        )

        self.assertEqual(agy_process.port_from_log(log), 61321)

    def test_no_confunde_el_puerto_de_grpc_con_el_de_http(self):
        """El de gRPC va por HTTPS y no sirve para hablar JSON plano."""
        log = (
            "Language server listening on random port at 61320 for HTTPS (gRPC)\n"
        )

        self.assertIsNone(agy_process.port_from_log(log))

    def test_sin_la_linea_todavia_no_hay_puerto(self):
        self.assertIsNone(agy_process.port_from_log("arrancando...\n"))


class _PtyFalso:
    def __init__(self):
        self.escrito = []

    def write(self, texto):
        self.escrito.append(texto)

    def isalive(self):
        return True


class TeclearElTurno(unittest.TestCase):
    def test_termina_con_un_retorno_para_enviarlo(self):
        pty = _PtyFalso()

        agy_process.type_text(pty, "hola")

        self.assertEqual("".join(pty.escrito), "hola\r")

    def test_los_saltos_de_linea_no_parten_el_mensaje(self):
        """Un salto de línea lo tomaría como enviar el turno a medias."""
        pty = _PtyFalso()

        agy_process.type_text(pty, "primero\nsegundo")

        enviado = "".join(pty.escrito)
        self.assertEqual(enviado, "primero segundo\r")
        self.assertEqual(enviado.count("\r"), 1)


class EsperarAQueEsteListo(unittest.TestCase):
    """Antes se esperaba a que la pantalla callara cuatro segundos, y a veces
    la CLI seguía inicializando: el primer mensaje tecleado se perdía. Ahora se
    espera a una señal de verdad, que el servidor anuncie su puerto."""

    def setUp(self):
        directorio = TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        self.log = Path(directorio.name) / "agy.log"

    def test_devuelve_el_puerto_en_cuanto_aparece(self):
        def escribir_luego():
            time.sleep(0.2)
            self.log.write_text(
                "listening on random port at 55001 for HTTP\n", encoding="utf-8"
            )

        threading.Thread(target=escribir_luego, daemon=True).start()

        self.assertEqual(agy_process.wait_for_port(self.log, timeout=5.0), 55001)

    def test_si_nunca_aparece_se_rinde(self):
        self.assertIsNone(agy_process.wait_for_port(self.log, timeout=0.3))


class EsperarAQueTermineDeArrancar(unittest.TestCase):
    """El puerto aparece antes de que la interfaz acepte que le tecleen.

    Medido: el servidor anuncia el puerto a los 3-5 s, pero la CLI sigue
    resolviendo el modelo hasta los 6,5 s, y lo que se teclee mientras se
    pierde. La señal buena es que el log deje de escribirse.
    """

    def setUp(self):
        directorio = TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        self.log = Path(directorio.name) / "agy.log"
        self.log.write_text("arrancando\n", encoding="utf-8")

    def test_espera_a_que_el_log_deje_de_crecer(self):
        def seguir_escribiendo():
            for _ in range(3):
                time.sleep(0.1)
                with self.log.open("a", encoding="utf-8") as fichero:
                    fichero.write("sigo inicializando\n")

        threading.Thread(target=seguir_escribiendo, daemon=True).start()

        inicio = time.time()
        listo = agy_process.wait_until_idle(self.log, quiet=0.3, timeout=5.0)

        self.assertTrue(listo)
        # No pudo darlo por listo antes de que el último escribiera.
        self.assertGreaterEqual(time.time() - inicio, 0.3)

    def test_si_no_para_nunca_se_rinde(self):
        parar = threading.Event()

        def escribir_sin_fin():
            while not parar.is_set():
                with self.log.open("a", encoding="utf-8") as fichero:
                    fichero.write("no paro\n")
                time.sleep(0.05)

        hilo = threading.Thread(target=escribir_sin_fin, daemon=True)
        hilo.start()
        self.addCleanup(parar.set)

        self.assertFalse(
            agy_process.wait_until_idle(self.log, quiet=0.5, timeout=1.0)
        )


class ComoSeLanzaAgy(unittest.TestCase):
    def test_el_comando_auto_aprueba_las_herramientas(self):
        """Nadie lee el pseudoterminal, así que nadie contestaría a un permiso.

        Sin este flag, en cuanto el modelo quiere usar una herramienta la CLI
        se queda preguntando a nadie y el turno muere de espera. Quien pone el
        límite aquí es el contenedor, no la pregunta.
        """
        capturado = {}

        def _pty_de_mentira(command, workspace):
            capturado["command"] = command
            return _PtyFalso()

        directorio = TemporaryDirectory()
        self.addCleanup(directorio.cleanup)

        with patch.object(agy_process, "_open_pty", _pty_de_mentira), patch.object(
            agy_process, "wait_for_port", return_value=4321
        ), patch.object(agy_process, "wait_until_idle", return_value=True):
            proceso = agy_process.AgyProcess.start(
                binary="agy", workspace=directorio.name,
                model="gemini-3.6-flash-low", effort="high",
            )

        self.assertIn("--dangerously-skip-permissions", capturado["command"])
        self.assertIn("--model", capturado["command"])
        self.assertIn("--effort", capturado["command"])
        self.assertIn("high", capturado["command"])
        self.assertEqual(proceso.port, 4321)


class CuandoAgyNoEstaInstalado(unittest.TestCase):
    """El usuario puede no tener `agy`: el turno debe poder irse a Claude."""

    def test_arrancar_un_binario_inexistente_da_un_error_reconocible(self):
        directorio = TemporaryDirectory()
        self.addCleanup(directorio.cleanup)

        with self.assertRaises(agy_process.AgyUnavailable):
            agy_process.AgyProcess.start(
                binary="agy-que-no-existe-12345",
                workspace=directorio.name,
                model="",
                timeout=5.0,
            )

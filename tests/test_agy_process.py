"""El proceso `agy`: encontrar su puerto y teclearle el turno."""
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

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

    def test_el_ritmo_sale_de_la_configuracion(self):
        """Hay que poder calibrarlo contra la CLI real y retroceder sin tocar código.

        Lo que se pierde al teclear rápido no lo ve un test: lo ve el texto que
        `agy` acaba registrando. Por eso el ritmo es un ajuste, no una constante.
        """
        pty = _PtyFalso()

        with patch.object(agy_process.settings, "agy_type_chunk", 4), patch.object(
            agy_process.settings, "agy_type_delay_ms", 0
        ):
            agy_process.type_text(pty, "doce caracteres")

        # Bloques de cuatro, y el retorno aparte.
        self.assertEqual(pty.escrito, ["doce", " car", "acte", "res", "\r"])

    def test_un_ritmo_invalido_no_deja_el_turno_sin_enviar(self):
        pty = _PtyFalso()

        with patch.object(agy_process.settings, "agy_type_chunk", 0), patch.object(
            agy_process.settings, "agy_type_delay_ms", -5
        ):
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
                model="gemini-3.6-flash", effort="high",
            )

        self.assertIn("--dangerously-skip-permissions", capturado["command"])
        self.assertIn("--model", capturado["command"])
        self.assertIn("--effort", capturado["command"])
        self.assertIn("high", capturado["command"])
        self.assertEqual(proceso.port, 4321)

    def test_no_se_manda_effort_si_el_modelo_ya_lo_lleva_en_el_nombre(self):
        """`agy` rechaza el flag y lo dice en cada arranque.

            common.go:331] failed to apply model override:
                           failed to resolve effort: --effort is not
                           supported for model "gemini-3.6-flash-low"

        El sufijo `-low` y `--effort low` son la misma palanca, así que
        mandar las dos solo servía para llenar el log de un error que no lo
        era y hacer más difícil leer los arranques de verdad rotos.
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
            agy_process.AgyProcess.start(
                binary="agy", workspace=directorio.name,
                model="gemini-3.6-flash-low", effort="low",
            )

        self.assertIn("--model", capturado["command"])
        self.assertIn("gemini-3.6-flash-low", capturado["command"])
        self.assertNotIn("--effort", capturado["command"])


class _PtyConGuion:
    """Un pseudoterminal que entrega lo que se le diga, errores incluidos.

    Al acabarse el guion da EOF, que es lo que hace el de verdad cuando el
    proceso se ha ido: `read` nunca devuelve vacío, o trae datos o lanza.
    """

    def __init__(self, guion):
        self.guion = list(guion)
        self.lecturas = 0

    def read(self, _size):
        self.lecturas += 1
        if not self.guion:
            raise EOFError("fin del pseudoterminal")
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente

    def isalive(self):
        return True


class VaciarLaSalidaDeAgy(unittest.TestCase):
    """Que nadie vacíe la salida es como se cuelga `agy` de verdad.

    Nadie lee el pseudoterminal para nada, pero hay que vaciarlo igual: cuando
    la salida llena su buffer —y a `agy` le basta repintar la pantalla—, la CLI
    se queda bloqueada escribiendo y deja de leer lo que se le teclea. El
    proceso sigue vivo, su language server sigue contestando, y el turno se
    teclea al vacío: es el «agy no registró el turno tecleado» que dejaba a
    Vibi contestando por Claude.

    Medido en el contenedor: un `agy` de dos horas con el pseudoterminal
    abierto y cero hilos leyéndolo.
    """

    def _drenando(self) -> threading.Event:
        marca = threading.Event()
        marca.set()
        return marca

    def test_un_error_de_lectura_no_termina_el_vaciado(self):
        """Rendirse al primer error es lo que dejaba a `agy` sin quien le vacíe.

        Cualquier excepción valía para matar el hilo, y ninguna dejaba rastro:
        un byte que no fuera UTF-8 válido bastaba.
        """
        pty = _PtyConGuion([OSError("lectura interrumpida"), "pantalla", "más"])

        agy_process._drain(pty)

        # Las tres del guion y la que topa con el EOF.
        self.assertEqual(pty.lecturas, 4)

    def test_una_lectura_sin_datos_no_gira_a_toda_maquina(self):
        """`pywinpty` puede volver sin datos en vez de esperar a que haya."""
        pty = _PtyConGuion(["", "", "pantalla"])

        with patch.object(agy_process.time, "sleep") as dormir:
            agy_process._drain(pty)

        self.assertEqual(dormir.call_count, 2)

    def test_el_fin_del_proceso_cierra_el_vaciado(self):
        pty = _PtyConGuion([])
        drenando = self._drenando()

        agy_process._drain(pty, drenando)

        self.assertFalse(drenando.is_set())

    def test_un_error_que_no_cesa_no_se_queda_girando(self):
        """Reintentar sin tope gastaría una CPU entera sin arreglar nada."""
        pty = _PtyConGuion([OSError("roto")] * 200)
        drenando = self._drenando()

        agy_process._drain(pty, drenando)

        self.assertLess(pty.lecturas, 200)
        self.assertFalse(drenando.is_set())

    def test_sin_nadie_vaciando_la_salida_el_proceso_no_esta_sano(self):
        """La comprobación de salud no miraba el camino que se rompe.

        Preguntarle al language server no sirve aquí: contesta igual de bien
        con la interfaz bloqueada, así que el proceso pasaba por sano y cada
        turno siguiente se volvía a teclear al vacío.
        """
        drenando = threading.Event()  # ya terminó: nadie vacía la salida
        proceso = agy_process.AgyProcess(
            _PtyFalso(), 4321, Path("agy.log"), drenando
        )
        cliente = Mock()
        cliente.conversations.return_value = []

        with patch.object(
            agy_process.agy_client, "AgyClient", return_value=cliente
        ):
            self.assertFalse(proceso.healthy())

        cliente.conversations.assert_not_called()


class GuardarElLogDelAgyCaido(unittest.TestCase):
    """El log del proceso caído es la única prueba de lo que pasó.

    Ahí consta si el turno tecleado llegó siquiera a entrar en la CLI
    (`HandleUserInput`), que es lo que distingue «se perdió por el camino» de
    «entró en la conversación equivocada». Borrarlo al matar el proceso lo
    destruía justo en el único momento en que hacía falta.
    """

    def setUp(self):
        directorio = TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        self.directorio = Path(directorio.name)
        self.log = self.directorio / "vibi-agy-abc123.log"
        self.log.write_text("HandleUserInput called with...\n", encoding="utf-8")
        self.proceso = agy_process.AgyProcess(_PtyFalso(), 4321, self.log)

    def _guardados(self):
        return sorted(self.directorio.glob(f"{agy_process.PREFIJO_LOG_CAIDO}*.log"))

    def test_al_caerse_el_log_se_aparta_en_vez_de_borrarse(self):
        self.proceso.kill(conservar_log=True)

        self.assertFalse(self.log.exists(), "el original se mueve, no se copia")
        guardados = self._guardados()
        self.assertEqual(len(guardados), 1)
        self.assertIn("HandleUserInput", guardados[0].read_text(encoding="utf-8"))

    def test_en_un_cierre_ordenado_no_hay_nada_que_investigar(self):
        self.proceso.kill()

        self.assertFalse(self.log.exists())
        self.assertEqual(self._guardados(), [])

    def test_no_se_acumulan_sin_fin(self):
        """Sin tope llenarían el disco del contenedor."""
        for numero in range(agy_process.LOGS_CAIDOS_QUE_SE_GUARDAN + 3):
            viejo = self.directorio / f"vibi-agy-{numero}.log"
            viejo.write_text("caído\n", encoding="utf-8")
            agy_process.AgyProcess(_PtyFalso(), 1, viejo).kill(conservar_log=True)

        self.assertEqual(
            len(self._guardados()), agy_process.LOGS_CAIDOS_QUE_SE_GUARDAN
        )

    def test_sin_log_que_guardar_no_revienta(self):
        self.log.unlink()

        self.proceso.kill(conservar_log=True)  # no debe lanzar

        self.assertEqual(self._guardados(), [])


class TolerarLoQuePintaLaInterfaz(unittest.TestCase):
    """`agy` pinta una interfaz entera por el pseudoterminal.

    `ptyprocess` construye su decodificador con `errors='strict'` y `spawn` no
    deja elegir otro, así que un byte a medias hacía que empezara a lanzar.
    """

    def test_un_byte_invalido_no_rompe_la_decodificacion(self):
        pty = Mock()
        pty.decoder = None

        agy_process._tolerar_bytes_invalidos(pty)

        self.assertEqual(pty.decoder.decode(b"hola \xff"), "hola �")

    def test_en_windows_no_hay_decodificador_que_tocar(self):
        """`pywinpty` entrega texto ya decodificado."""

        class _SinDecoder:
            pass

        pty = _SinDecoder()

        agy_process._tolerar_bytes_invalidos(pty)  # no debe reventar

        self.assertFalse(hasattr(pty, "decoder"))


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

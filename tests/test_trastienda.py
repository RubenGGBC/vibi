"""El escritorio invisible donde Vibi trabaja sin que se le vea.

Estas pruebas crean un escritorio de Windows de verdad y lanzan el Bloc de
notas dentro. Son lentas comparadas con las demás —unos segundos— y no corren
fuera de Windows, pero no hay forma de fingir esto: lo que se está probando es
justamente que el sistema lo permita.

**No abren nada en la pantalla del usuario**, que es todo el asunto: si alguna
de estas ventanas apareciera, la prueba habría fallado por definición.
"""
from __future__ import annotations

import platform
import sys
import time
from pathlib import Path
from unittest import TestCase, skipUnless

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

if platform.system() == "Windows":
    from vibi_node import trastienda, ui_windows
else:  # pragma: no cover - depende del sistema
    trastienda = ui_windows = None

soloWindows = skipUnless(platform.system() == "Windows", "Windows manda aquí")


@soloWindows
class MontarLaTrastienda(TestCase):
    def test_se_abre_y_se_reutiliza(self):
        primero = trastienda.abrir()
        segundo = trastienda.abrir()

        self.assertTrue(primero)
        self.assertEqual(primero, segundo, "no puede haber dos trastiendas")

    def test_existe_lo_dice(self):
        trastienda.abrir()

        self.assertTrue(trastienda.existe())


@soloWindows
class TrabajarDentro(TestCase):
    """`dentro()` conmuta el hilo, y solo funciona en uno limpio.

    Cada prueba corre en un hilo recién creado a propósito: el hilo principal
    de los tests ya ha usado UIA, y entonces `SetThreadDesktop` se niega con
    `ERROR_BUSY`. No es un apaño del test, es el contrato de la función — y el
    motivo de que exista `ejecutar()`, que es lo que usa todo lo demás.
    """

    def _en_un_hilo_limpio(self, funcion):
        import threading

        salida = {}

        def correr():
            try:
                salida["valor"] = funcion()
            except BaseException as error:  # noqa: BLE001
                salida["error"] = error

        hilo = threading.Thread(target=correr)
        hilo.start()
        hilo.join(timeout=20)
        if "error" in salida:
            raise salida["error"]
        return salida.get("valor")

    def test_el_hilo_entra_y_vuelve(self):
        import ctypes

        def prueba():
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            antes = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
            with trastienda.dentro():
                dentro = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
            despues = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
            return antes, dentro, despues

        antes, dentro, despues = self._en_un_hilo_limpio(prueba)

        self.assertNotEqual(dentro, antes)
        self.assertEqual(despues, antes)

    def test_vuelve_aunque_algo_reviente(self):
        import ctypes

        def prueba():
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            antes = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
            try:
                with trastienda.dentro():
                    raise ValueError("algo salió mal ahí dentro")
            except ValueError:
                pass
            return antes, user32.GetThreadDesktop(kernel32.GetCurrentThreadId())

        antes, despues = self._en_un_hilo_limpio(prueba)

        self.assertEqual(despues, antes)

    def test_un_hilo_que_ya_ha_dibujado_no_entra_y_lo_dice(self):
        """Y el error tiene que nombrar la salida, o cuesta un rato entenderlo."""
        ui_windows.ventanas()  # esto hace que UIA cree sus ventanas ocultas

        try:
            with trastienda.dentro():
                pass
        except trastienda.ErrorTrastienda as error:
            self.assertIn("ejecutar", str(error))
        # Si no levanta, este hilo estaba limpio: tampoco es un fallo.


@soloWindows
class LoQueSeAbreAhiNoSeVe(TestCase):
    """La prueba que da sentido a todo esto."""

    def setUp(self):
        self.pid = trastienda.lanzar("notepad.exe")
        time.sleep(1.5)
        self.addCleanup(self._cerrar)

    def _cerrar(self):
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0001, False, self.pid)
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)

    def test_no_aparece_en_el_escritorio_del_usuario(self):
        titulos = [v.titulo.lower() for v in ui_windows.ventanas()]
        intrusas = [t for t in titulos if "bloc de notas" in t or "notepad" in t]

        self.assertEqual(
            intrusas, [], f"se ha colado en la pantalla del usuario: {intrusas}"
        )

    def test_pero_desde_dentro_sí_se_ve(self):
        # Por `ejecutar` y no por `dentro()`: este hilo ya ha usado UIA al
        # mirar el escritorio del usuario, y entonces `SetThreadDesktop` se
        # niega con ERROR_BUSY. Es justo el motivo de que exista el hilo.
        titulos = trastienda.ejecutar(
            lambda: [v.titulo.lower() for v in ui_windows.ventanas()]
        )

        self.assertTrue(
            any("bloc de notas" in t or "notepad" in t for t in titulos),
            f"no está ni dentro: {titulos[:6]}",
        )


@soloWindows
class LoQueNoSePuede(TestCase):
    """La frontera del diseño, escrita como prueba para que no se olvide.

    Medido el 20/08/2026 con la Calculadora: lanzada desde la trastienda,
    **aparece en el escritorio del usuario**. No falla — se escapa, que es
    peor: le sale una ventana en la pantalla sin haberla pedido. El motivo es
    que `shell:AppsFolder` no arranca la aplicación, se lo pide al explorador,
    y el explorador vive en el escritorio de siempre.
    """

    def test_una_app_de_la_store_se_rechaza_antes_de_intentarlo(self):
        with self.assertRaises(trastienda.ErrorTrastienda) as caso:
            trastienda.lanzar(
                "explorer.exe shell:AppsFolder\\Microsoft.WindowsCalculator!App"
            )

        mensaje = str(caso.exception).lower()
        self.assertIn("store", mensaje)
        # Y tiene que decir dónde acabaría, o parece un capricho.
        self.assertIn("escritorio", mensaje)

    def test_el_explorador_a_secas_tampoco(self):
        """Cualquier cosa que delegue en el explorador se escapa igual."""
        with self.assertRaises(trastienda.ErrorTrastienda):
            trastienda.lanzar("explorer.exe C:\\Users")

"""Fotografiar una ventana concreta, exista o no una pantalla donde se vea.

La captura de siempre (`screen.capturar`) fotografía la pantalla física con
`mss`, y eso no sirve para la trastienda: ahí no hay pantalla. Lo que sí sirve
es pedirle a la propia ventana que se dibuje, con `PrintWindow`, que es lo que
usan las herramientas de grabación para capturar una ventana tapada.

Comprobado el 20/08/2026 sobre un Opera abierto en la trastienda: 1936x1048
capturados sin que hubiera nada en pantalla.

Y hay una vuelta de tuerca que importa: `PrintWindow` con `PW_RENDERFULLCONTENT`
—el 2— es lo único que captura contenido de Chromium y de las apps que dibujan
por GPU. Sin ese flag, media aplicación moderna sale en negro.
"""
from __future__ import annotations

import platform
import sys
import time
from pathlib import Path
from unittest import TestCase, skipUnless

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

if platform.system() == "Windows":
    from vibi_node import screen, trastienda, ui_windows
else:  # pragma: no cover
    screen = trastienda = ui_windows = None

soloWindows = skipUnless(platform.system() == "Windows", "Windows manda aquí")


@soloWindows
class FotografiarUnaVentana(TestCase):
    def setUp(self):
        self.destino = Path(__file__).parent / "_captura_de_prueba.jpg"
        self.addCleanup(
            lambda: self.destino.exists() and self.destino.unlink()
        )

    def _alguna_ventana(self):
        ventanas = [v for v in ui_windows.ventanas() if not v.minimizada]
        if not ventanas:
            self.skipTest("no hay ninguna ventana visible que fotografiar")
        return max(
            ventanas,
            key=lambda v: (v.rect.derecha - v.rect.izquierda)
            * (v.rect.abajo - v.rect.arriba),
        )

    def test_una_ventana_del_escritorio_normal_se_fotografía(self):
        ventana = self._alguna_ventana()

        salida = screen.capturar_ventana(ventana.handle, self.destino)

        self.assertTrue(self.destino.exists())
        self.assertGreater(self.destino.stat().st_size, 1000)
        self.assertGreater(salida["ancho"], 0)

    def test_un_handle_que_no_existe_lo_dice(self):
        with self.assertRaises(screen.ErrorPantalla) as caso:
            screen.capturar_ventana(999_999_999, self.destino)

        self.assertIn("ventana", str(caso.exception).lower())

    def test_la_imagen_se_reduce_como_las_demás(self):
        """Una captura de 4K entera no cabe por el canal ni le sirve al modelo."""
        ventana = self._alguna_ventana()

        salida = screen.capturar_ventana(ventana.handle, self.destino)

        self.assertLessEqual(max(salida["ancho"], salida["alto"]), screen.LADO_MAXIMO)


@soloWindows
class FotografiarEnLaTrastienda(TestCase):
    """Lo que da sentido a todo: ver lo que no está en ninguna pantalla."""

    def setUp(self):
        self.destino = Path(__file__).parent / "_captura_trastienda.jpg"
        self.pid = trastienda.lanzar("notepad.exe")
        time.sleep(1.8)
        self.addCleanup(self._limpiar)

    def _limpiar(self):
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0001, False, self.pid)
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)
        if self.destino.exists():
            self.destino.unlink()

    def test_se_fotografía_una_ventana_que_nadie_ve(self):
        def dentro_de_la_trastienda():
            ventanas = [
                v for v in ui_windows.ventanas()
                if "notas" in v.titulo.lower() or "notepad" in v.titulo.lower()
            ]
            if not ventanas:
                return None
            return screen.capturar_ventana(ventanas[0].handle, self.destino)

        salida = trastienda.ejecutar(dentro_de_la_trastienda)
        if salida is None:
            self.skipTest("el Bloc de notas no llegó a abrirse")

        self.assertTrue(self.destino.exists())
        self.assertGreater(self.destino.stat().st_size, 1000)
        self.assertGreater(salida["ancho"], 0)

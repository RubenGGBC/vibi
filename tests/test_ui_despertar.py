"""Cuánto se espera a que una ventana publique su árbol, y a cuáles se espera.

Hay dos situaciones que un presupuesto fijo no distingue y que quieren lo
contrario: una ventana pequeña de verdad —una bandeja, un diálogo— que ya ha
dicho todo lo que tiene, y una de Chromium recién abierta que todavía no ha
construido el suyo. Medido en este equipo el 2026-08-15: la primera pagaba
600 ms de espera para nada, y a la segunda le faltaban 250.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

if platform.system() == "Windows":
    from vibi_node import ui_tree, ui_windows  # noqa: E402
else:  # pragma: no cover - depende del sistema
    ui_windows = ui_tree = None


@skipUnless(platform.system() == "Windows", "UIA solo existe en Windows")
class QueVentanasPuedenDormir(TestCase):
    """La clase de Win32 es lo que separa los dos casos, y se midió."""

    def test_chromium_y_gecko_pueden_dormir(self):
        for clase in (
            "Chrome_WidgetWin_1",   # VS Code, Discord, Electron en general
            "Chrome_WidgetWin_0",
            "MozillaWindowClass",   # Zen, Firefox
        ):
            with self.subTest(clase=clase):
                self.assertTrue(ui_windows.clase_perezosa(clase))

    def test_lo_nativo_no_duerme(self):
        for clase in (
            "HwndWrapper[Raycast;Main;fd8f]",   # WPF
            "Qt5QWindowIcon",                   # BakkesMod
            "CASCADIA_HOSTING_WINDOW_CLASS",    # Windows Terminal
            "local.morgana.companion-sic",      # el companion de Vibi
            "Notepad",
            "",
        ):
            with self.subTest(clase=clase):
                self.assertFalse(ui_windows.clase_perezosa(clase))


@skipUnless(platform.system() == "Windows", "UIA solo existe en Windows")
class Despertar(TestCase):
    """Con el recorrido simulado, para medir decisiones y no ventanas."""

    def _arbol(self, cuantos: int):
        """Un árbol con `cuantos` nodos contados por `ui_tree.contar`."""
        hijos = tuple(
            ui_tree.Nodo(rol="button", nombre=f"n{i}", valor=None,
                         estado=frozenset(), rect=ui_tree.Rect(0, 0, 1, 1),
                         accionable=True, hijos=(), nativo=None, identidad=(i,))
            for i in range(max(0, cuantos - 1))
        )
        return ui_tree.Nodo(rol="window", nombre="raiz", valor=None,
                            estado=frozenset(), rect=ui_tree.Rect(0, 0, 9, 9),
                            accionable=False, hijos=hijos, nativo=None,
                            identidad=("raiz",))

    def test_una_ventana_pequena_que_no_duerme_no_espera(self):
        arbol = self._arbol(8)
        with patch.object(ui_windows, "_traer_arbol", return_value=arbol) as traer, \
             patch.object(ui_windows.time, "sleep") as dormir:
            ui_windows._despertar(None, ui_tree.Rect(0, 0, 9, 9), puede_dormir=False)
        self.assertEqual(traer.call_count, 1, "un solo recorrido")
        dormir.assert_not_called()

    def test_una_ventana_grande_no_espera_aunque_pueda_dormir(self):
        arbol = self._arbol(200)
        with patch.object(ui_windows, "_traer_arbol", return_value=arbol) as traer, \
             patch.object(ui_windows.time, "sleep") as dormir:
            ui_windows._despertar(None, ui_tree.Rect(0, 0, 9, 9), puede_dormir=True)
        self.assertEqual(traer.call_count, 1)
        dormir.assert_not_called()

    def test_una_chromium_dormida_se_espera_hasta_que_publica(self):
        """Reproduce la curva medida: meseta plana y después salto."""
        respuestas = [self._arbol(16)] * 12 + [self._arbol(170)]
        with patch.object(ui_windows, "_traer_arbol", side_effect=respuestas), \
             patch.object(ui_windows.time, "sleep") as dormir:
            arbol = ui_windows._despertar(
                None, ui_tree.Rect(0, 0, 9, 9), puede_dormir=True
            )
        self.assertGreaterEqual(ui_tree.contar(arbol), ui_windows.MINIMO_CREIBLE)
        # Aguantó la meseta en vez de rendirse en ella.
        self.assertGreaterEqual(dormir.call_count, 12)

    def test_el_presupuesto_cubre_la_curva_medida(self):
        """844 ms tardó el árbol de VS Code en aparecer. Con margen."""
        self.assertGreater(
            ui_windows.PRESUPUESTO_DESPERTAR, 1.0,
            "600 ms se rendían justo antes de que el árbol existiera",
        )

    def test_una_chromium_muda_se_rinde_y_devuelve_lo_que_hay(self):
        with patch.object(ui_windows, "_traer_arbol", return_value=self._arbol(3)), \
             patch.object(ui_windows.time, "sleep"):
            arbol = ui_windows._despertar(
                None, ui_tree.Rect(0, 0, 9, 9), puede_dormir=True
            )
        self.assertEqual(ui_tree.contar(arbol), 3)


@skipUnless(platform.system() == "Windows", "UIA solo existe en Windows")
class MemoriaDeMudas(TestCase):
    """Una ventana perezosa pero muda no puede cobrar el presupuesto siempre.

    Discord es `Chrome_WidgetWin_1`, está visible y publica 8 nodos: trae la
    accesibilidad apagada, no dormida. Sin memoria pagaría 2,5 s en cada
    vistazo, que es peor que los 660 ms de antes.
    """

    def setUp(self):
        ui_windows.olvidar_mudas()
        self.addCleanup(ui_windows.olvidar_mudas)

    def test_la_primera_vez_no_se_sabe_y_se_espera(self):
        self.assertFalse(ui_windows._se_quedo_muda(1234))

    def test_despues_de_esperar_en_vano_se_recuerda(self):
        ui_windows._recordar_mudez(1234, muda=True)
        self.assertTrue(ui_windows._se_quedo_muda(1234))

    def test_una_ventana_que_despierta_no_queda_marcada(self):
        ui_windows._recordar_mudez(1234, muda=True)
        ui_windows._recordar_mudez(1234, muda=False)
        self.assertFalse(ui_windows._se_quedo_muda(1234))

    def test_la_marca_caduca(self):
        ui_windows._recordar_mudez(1234, muda=True)
        futuro = ui_windows.time.monotonic() + ui_windows.MEMORIA_MUDAS + 1
        with patch.object(ui_windows.time, "monotonic", return_value=futuro):
            self.assertFalse(ui_windows._se_quedo_muda(1234))

    def test_cada_ventana_va_por_su_cuenta(self):
        ui_windows._recordar_mudez(1234, muda=True)
        self.assertFalse(ui_windows._se_quedo_muda(5678))

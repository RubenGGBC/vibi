"""Fotografiar una ventana concreta en un Mac.

Antes `screen.capture` con `ventana` iba siempre por `ui_windows` y en macOS
acababa en «module 'ctypes' has no attribute 'windll'». Aquí se prueba qué
ventana se elige y qué se le pide a `screencapture`, sin fotografiar nada.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import capabilities, screen  # noqa: E402

VENTANAS = [
    {"id": 11, "app": "Vibi", "titulo": "Vibi", "x": 0, "y": 0,
     "ancho": 800, "alto": 600},
    # WhatsApp pone un U+200E delante de sus nombres.
    {"id": 42, "app": "WhatsApp", "titulo": "‎WhatsApp", "x": 100,
     "y": 50, "ancho": 1200, "alto": 800},
    {"id": 7, "app": "Google Chrome", "titulo": "Introducing Opper", "x": 0,
     "y": 0, "ancho": 1400, "alto": 900},
]


class ElegirVentana(TestCase):
    def test_sin_decir_cual_es_la_de_delante(self):
        self.assertEqual(screen.elegir_ventana_mac(VENTANAS, "")["id"], 11)

    def test_por_nombre_sin_marcas_invisibles_ni_mayusculas(self):
        self.assertEqual(screen.elegir_ventana_mac(VENTANAS, "whatsapp")["id"], 42)

    def test_por_titulo_o_por_aplicacion(self):
        self.assertEqual(screen.elegir_ventana_mac(VENTANAS, "opper")["id"], 7)
        self.assertEqual(screen.elegir_ventana_mac(VENTANAS, "chrome")["id"], 7)

    def test_si_no_esta_dice_cuales_hay(self):
        with self.assertRaisesRegex(screen.ErrorPantalla, "WhatsApp"):
            screen.elegir_ventana_mac(VENTANAS, "Telegram")


class FotografiarLaVentana(TestCase):
    def test_pide_esa_ventana_sin_sombra_y_devuelve_su_geometria(self):
        destino = Path("/tmp/no-se-escribe.jpg")
        with patch.object(screen, "_ventanas_mac", return_value=VENTANAS), \
             patch.object(screen.shutil, "which", return_value="/usr/sbin/screencapture"), \
             patch.object(screen, "_screencapture") as lanzar, \
             patch.object(screen, "_reducir_mac", return_value=(1176, 784)):
            detalle = screen.capturar_ventana_mac("WhatsApp", destino)

        orden = lanzar.call_args[0][0]
        self.assertEqual(orden[orden.index("-l") + 1], "42")
        self.assertIn("-o", orden)
        self.assertIn("-x", orden)
        self.assertEqual(
            detalle,
            {
                "ancho": 1176, "alto": 784,
                "ancho_real": 1200, "alto_real": 800,
                "origen_x": 100, "origen_y": 50,
                "titulo": "‎WhatsApp",
            },
        )


class LaCapacidadEnUnMac(TestCase):
    def setUp(self):
        screen.olvidar_mapa()
        self.addCleanup(screen.olvidar_mapa)

    def test_no_pasa_por_ui_windows_y_deja_el_mapa_para_tocar(self):
        def falsa(selector, destino):
            destino.write_bytes(b"\xff\xd8jpeg")
            return {
                "ancho": 600, "alto": 400, "ancho_real": 1200,
                "alto_real": 800, "origen_x": 100, "origen_y": 50,
                "titulo": "WhatsApp",
            }

        with patch.object(capabilities.platform, "system", return_value="Darwin"), \
             patch.object(screen, "capturar_ventana_mac", side_effect=falsa):
            salida = capabilities._capturar_una_ventana({"ventana": "WhatsApp"})

        self.assertEqual(salida["jpeg"], b"\xff\xd8jpeg")
        self.assertEqual(salida["detalle"]["descrita"], "la ventana «WhatsApp»")
        self.assertEqual(screen.mapa_actual(), "100,50,1200,800,600,400")

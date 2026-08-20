"""La agenda de qué aplicación se deja hablar por dentro y en qué puerto.

Lo que se prueba aquí es la contabilidad —quién es Chromium, qué puerto le toca,
cómo se le encuentra después— y no la conversación, que es `cdp` y necesita una
aplicación de verdad al otro lado.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import web_apps  # noqa: E402


class BaseAgenda(TestCase):
    def setUp(self):
        web_apps._agenda.clear()
        self.addCleanup(web_apps._agenda.clear)
        # Todos los puertos libres, para no depender de la máquina.
        parche = patch(
            "vibi_node.browser_mcp.escuchando", return_value=False
        )
        parche.start()
        self.addCleanup(parche.stop)


class QuienEsChromium(TestCase):
    def test_las_que_lo_son(self):
        for nombre in (
            "Discord", "Slack", "Visual Studio Code", "Spotify",
            "Notion", "Obsidian", "WhatsApp",
        ):
            with self.subTest(nombre=nombre):
                self.assertTrue(web_apps.es_chromium(nombre), nombre)

    def test_las_que_no(self):
        """Añadirle un flag desconocido a esto puede impedir que arranque."""
        for nombre in (
            "Bloc de notas", "RPCS3", "Fortnite", "BakkesMod",
            "Photoshop", "", "Steam",
        ):
            with self.subTest(nombre=nombre):
                self.assertFalse(web_apps.es_chromium(nombre), nombre)


class RepartirPuertos(BaseAgenda):
    def test_cada_aplicación_recibe_el_suyo(self):
        uno = web_apps.reservar("Discord")
        otro = web_apps.reservar("Spotify")

        self.assertNotEqual(uno, otro)
        self.assertGreaterEqual(uno, web_apps.PRIMER_PUERTO)

    def test_la_misma_aplicación_reutiliza_el_suyo(self):
        """Relanzar Discord no puede dejar dos entradas apuntando a sitios."""
        primero = web_apps.reservar("Discord")
        segundo = web_apps.reservar("discord")

        self.assertEqual(primero, segundo)

    def test_no_se_reparte_uno_ocupado(self):
        with patch(
            "vibi_node.browser_mcp.escuchando",
            side_effect=lambda p, **k: p == web_apps.PRIMER_PUERTO,
        ):
            puerto = web_apps.reservar("Discord")

        self.assertNotEqual(puerto, web_apps.PRIMER_PUERTO)

    def test_el_flag_es_el_que_entiende_chromium(self):
        self.assertEqual(
            web_apps.flag_de_depuracion(9350), "--remote-debugging-port=9350"
        )


class EncontrarlaDespues(BaseAgenda):
    def test_por_su_nombre(self):
        puerto = web_apps.reservar("Discord")

        self.assertEqual(web_apps.puerto_de("Discord"), puerto)

    def test_por_un_trozo_del_nombre(self):
        """Una persona dice «vs code», no «Visual Studio Code»."""
        puerto = web_apps.reservar("Visual Studio Code")

        self.assertEqual(web_apps.puerto_de("visual studio"), puerto)

    def test_el_navegador_siempre_está(self):
        self.assertEqual(
            web_apps.puerto_de("el navegador"), web_apps.PUERTO_NAVEGADOR
        )

    def test_una_que_no_se_ha_lanzado_no_está(self):
        self.assertIsNone(web_apps.puerto_de("Photoshop"))

    def test_olvidar_la_quita(self):
        web_apps.reservar("Discord")
        web_apps.olvidar("Discord")

        self.assertIsNone(web_apps.puerto_de("Discord"))


class LoQueDeVerdadContesta(BaseAgenda):
    """La agenda dice quién debería estar; el puerto dice quién está."""

    def test_una_apuntada_que_ya_no_contesta_no_se_lista(self):
        web_apps.reservar("Discord")
        from vibi_node import cdp

        with patch(
            "vibi_node.cdp.pestanas", side_effect=cdp.ErrorCDP("no contesta")
        ):
            self.assertEqual(web_apps.disponibles(), [])

    def test_se_lista_con_sus_pestañas(self):
        web_apps.reservar("Discord")

        with patch(
            "vibi_node.cdp.pestanas",
            return_value=[{"title": "#general", "url": "https://discord.com/"}],
        ):
            vivos = web_apps.disponibles()

        self.assertTrue(any(v["app"] == "discord" for v in vivos))
        for entrada in vivos:
            self.assertEqual(entrada["pestanas"][0]["titulo"], "#general")

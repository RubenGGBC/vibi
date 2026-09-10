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
            "Notion", "Obsidian",
        ):
            with self.subTest(nombre=nombre):
                self.assertTrue(web_apps.es_chromium(nombre), nombre)

    def test_las_que_no(self):
        """Añadirle un flag desconocido a esto puede impedir que arranque."""
        for nombre in (
            "Bloc de notas", "RPCS3", "Fortnite", "BakkesMod",
            "Photoshop", "", "Steam",
            # Comprobado el 2026-09-08: el paquete de macOS es nativo
            # (`WAAppKitBridge.framework`, sin Electron ni CEF). El flag de
            # depuración no lo entiende y abrirla así da una segunda
            # instancia en vez de traer la que ya estaba abierta.
            "WhatsApp",
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


class DescubrirWebView2(TestCase):
    """Las aplicaciones que abren su puerto solas, sin que las lance Vibi.

    Una app WebView2 con la política del registro puesta arranca ya con el
    puerto abierto —la abra quien la abra— y escribe cuál en su
    `DevToolsActivePort`. Leerlo es lo que levanta la frontera de que «solo se
    puede hablar con lo que abrió Vibi».
    """

    def setUp(self):
        import tempfile

        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.raiz, True))

    def _paquete(self, nombre: str, contenido: str | None) -> Path:
        carpeta = self.raiz / nombre / "LocalCache" / "EBWebView"
        carpeta.mkdir(parents=True)
        if contenido is not None:
            (carpeta / "DevToolsActivePort").write_text(contenido)
        return carpeta

    def test_encuentra_el_puerto_que_la_app_dejo_escrito(self):
        self._paquete(
            "5319275A.WhatsAppDesktop_cv1g1gvanyjgm",
            "59500\n/devtools/browser/88e5c3a5-98dc-40d6-abf3-a19928a4fffd\n",
        )

        with patch("vibi_node.web_apps._contesta_un_chromium", return_value=True):
            encontradas = web_apps.descubrir_webview2([self.raiz])

        self.assertEqual(encontradas, {"whatsappdesktop": 59500})

    def test_una_sin_puerto_escrito_no_aparece(self):
        """Instalada pero cerrada: tiene el directorio y no el archivo."""
        self._paquete("5319275A.WhatsAppDesktop_cv1g1gvanyjgm", None)

        with patch("vibi_node.web_apps._contesta_un_chromium", return_value=True):
            self.assertEqual(web_apps.descubrir_webview2([self.raiz]), {})

    def test_un_archivo_con_basura_no_tumba_el_descubrimiento(self):
        self._paquete("Alguna.App_1", "no soy un puerto")
        self._paquete("5319275A.WhatsAppDesktop_cv1g1gvanyjgm", "59500\n")

        with patch("vibi_node.web_apps._contesta_un_chromium", return_value=True):
            encontradas = web_apps.descubrir_webview2([self.raiz])

        self.assertEqual(encontradas, {"whatsappdesktop": 59500})

    def test_un_puerto_imposible_se_descarta(self):
        """El archivo lo escribe la app, pero cualquiera puede sobrescribirlo."""
        for valor in ("0", "-1", "99999", "70000"):
            with self.subTest(valor=valor):
                raiz = self.raiz / valor
                (raiz / "X.App_1" / "LocalCache" / "EBWebView").mkdir(parents=True)
                (
                    raiz / "X.App_1" / "LocalCache" / "EBWebView"
                    / "DevToolsActivePort"
                ).write_text(valor)

                with patch(
                    "vibi_node.web_apps._contesta_un_chromium", return_value=True
                ):
                    self.assertEqual(web_apps.descubrir_webview2([raiz]), {})

    def test_no_se_fia_de_un_puerto_donde_no_contesta_un_chromium(self):
        """La defensa que importa: ese archivo es un puntero que alguien puede
        cambiar, y seguirlo a ciegas sería mandarle comandos a otro servicio."""
        self._paquete("X.App_1", "8080\n")

        with patch("vibi_node.web_apps._contesta_un_chromium", return_value=False):
            self.assertEqual(web_apps.descubrir_webview2([self.raiz]), {})


class LasDescubiertasSeUsanComoLasDemas(BaseAgenda):
    """De nada sirve descubrir un puerto si el resto del módulo no lo ve."""

    def test_puerto_de_encuentra_una_que_vibi_no_lanzo(self):
        with patch(
            "vibi_node.web_apps.descubrir_webview2",
            return_value={"whatsappdesktop": 59500},
        ):
            self.assertEqual(web_apps.puerto_de("WhatsApp"), 59500)

    def test_disponibles_lista_una_que_vibi_no_lanzo(self):
        with patch(
            "vibi_node.web_apps.descubrir_webview2",
            return_value={"whatsappdesktop": 59500},
        ), patch(
            "vibi_node.cdp.pestanas",
            return_value=[{"title": "WhatsApp", "url": "https://web.whatsapp.com/"}],
        ):
            vivas = web_apps.disponibles()

        self.assertTrue(
            any(v["app"] == "whatsappdesktop" and v["puerto"] == 59500 for v in vivas),
            vivas,
        )

    def test_la_agenda_manda_sobre_lo_descubierto(self):
        """Si Vibi la lanzó, ese es el puerto que conoce y el que vale."""
        web_apps._agenda["whatsappdesktop"] = 9350

        with patch(
            "vibi_node.web_apps.descubrir_webview2",
            return_value={"whatsappdesktop": 59500},
        ):
            self.assertEqual(web_apps.puerto_de("whatsappdesktop"), 9350)

"""Catálogo seguro de aplicaciones del agente Windows."""
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import app_catalog, client  # noqa: E402
from vibi_node.config import NodeConfig  # noqa: E402


def _entry(
    app_id: str,
    label: str,
    aliases: tuple[str, ...],
    kind: str = "shortcut",
    target: str | None = None,
) -> app_catalog.AppEntry:
    return app_catalog.AppEntry(
        id=app_id,
        label=label,
        aliases=aliases,
        launch_kind=kind,
        target=target or f"{label}.lnk",
    )


class NormalizarAlias(TestCase):
    def test_quita_acentos_articulos_y_espacios(self):
        self.assertEqual(app_catalog.normalize_alias("  La  Cálculadora "), "calculadora")

    def test_no_quita_un_articulo_pegado_al_nombre(self):
        self.assertEqual(app_catalog.normalize_alias("Elgato Control"), "elgato control")


class ResolverYArrancar(TestCase):
    def test_catalogo_frio_no_intenta_lanzar(self):
        launched = []
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (), launcher=lambda entry, extra=(): launched.append(entry.target)
        )

        self.assertEqual(catalog.launch("Spotify")["status"], "catalog_starting")
        self.assertEqual(launched, [])

    def test_alias_exacto_unico_lanza_el_objetivo_del_catalogo(self):
        launched = []
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (_entry("app_1", "Spotify", ("spotify",)),),
            launcher=lambda entry, extra=(): launched.append(entry.target),
        )
        catalog.refresh()

        result = catalog.launch("Spótify")

        self.assertEqual(result["status"], "launched")
        self.assertEqual(result["app"], {"id": "app_1", "label": "Spotify"})
        self.assertEqual(launched, ["Spotify.lnk"])
        self.assertNotIn("target", repr(result))

    def test_identificador_opaco_tambien_resuelve(self):
        launched = []
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (_entry("app_abc", "Spotify", ("spotify",)),),
            launcher=lambda entry, extra=(): launched.append(entry.id),
        )
        catalog.refresh()

        self.assertEqual(catalog.launch("app_abc")["status"], "launched")
        self.assertEqual(launched, ["app_abc"])

    def test_la_misma_app_por_dos_atajos_no_es_ambigua(self):
        """Medido el 20/08/2026: Discord salía tres veces en el catálogo.

        Dos accesos directos —uno del menú de inicio del usuario, otro del de
        todos— y su entrada empaquetada, los tres apuntando al mismo programa.
        Eso hacía que `catalog.launch("Discord")` devolviera «ambiguo» y no
        abriera nada, y que la trastienda no pudiera resolver ni un nombre.
        Dos entradas que llevan al mismo sitio no son una elección.
        """
        launched = []
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (
                _entry("app_1", "Discord", ("discord",),
                       target=r"C:\Users\x\Discord\Update.exe"),
                _entry("app_2", "Discord", ("discord",),
                       target=r"C:\Users\X\discord\update.EXE"),
            ),
            launcher=lambda entry, extra=(): launched.append(entry.id),
        )
        catalog.refresh()

        salida = catalog.launch("Discord")

        self.assertEqual(salida["status"], "launched", salida)
        self.assertEqual(len(launched), 1)

    def test_dos_programas_distintos_con_el_mismo_nombre_sí_preguntan(self):
        """Dos «chrome» de verdad —Google Chrome y Helium— en esta máquina."""
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (
                _entry("app_1", "chrome", ("chrome",),
                       target=r"C:\Program Files\Google\chrome.exe"),
                _entry("app_2", "chrome", ("chrome",),
                       target=r"C:\Users\x\Helium\chrome.exe"),
            ),
            launcher=lambda entry, extra=(): None,
        )
        catalog.refresh()

        self.assertEqual(catalog.launch("chrome")["status"], "ambiguous")

    def test_dos_alias_exacto_no_lanzan_nada(self):
        launched = []
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (
                _entry("app_1", "Terminal", ("terminal",)),
                _entry("app_2", "Terminal Preview", ("terminal",)),
            ),
            launcher=lambda entry, extra=(): launched.append(entry.id),
        )
        catalog.refresh()

        result = catalog.launch("Terminal")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(
            result["candidates"],
            [
                {"id": "app_1", "label": "Terminal"},
                {"id": "app_2", "label": "Terminal Preview"},
            ],
        )
        self.assertEqual(launched, [])

    def test_la_misma_etiqueta_con_objetivos_distintos_sigue_siendo_ambigua(self):
        launched = []
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (
                _entry(
                    "app_registry",
                    "Visual Studio Code",
                    ("visual studio code",),
                    kind="app_path",
                    target="Code.exe",
                ),
                _entry(
                    "app_start_menu",
                    "Visual Studio Code",
                    ("visual studio code",),
                    kind="shortcut",
                    target="Visual Studio Code.lnk",
                ),
            ),
            launcher=lambda entry, extra=(): launched.append(entry.id),
        )
        catalog.refresh()

        result = catalog.launch("Visual Studio Code")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(launched, [])

    def test_coincidencias_parciales_se_acotan_y_no_lanzan(self):
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: tuple(
                _entry(f"app_{index}", f"Visual {index}", (f"visual {index}",))
                for index in range(8)
            ),
            launcher=lambda entry, extra=(): self.fail(f"No debía lanzar {entry}"),
        )
        catalog.refresh()

        result = catalog.launch("Visual")

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(len(result["candidates"]), 5)

    def test_ruta_argumento_o_comando_no_llegan_al_lanzador(self):
        launched = []
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (_entry("app_1", "Spotify", ("spotify",)),),
            launcher=lambda entry, extra=(): launched.append(entry.id),
        )
        catalog.refresh()

        for query in (
            r"C:\\Windows\\System32\\calc.exe",
            "Spotify --private-session",
            "Spotify & calc.exe",
            "informe.pdf",
            "https://spotify.com",
        ):
            with self.subTest(query=query):
                self.assertEqual(catalog.launch(query)["status"], "not_found")
        self.assertEqual(launched, [])

    def test_fallo_del_sistema_devuelve_resultado_tipado(self):
        def fail(_entry, _extra=()):
            raise OSError("Windows dijo que no")

        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (_entry("app_1", "Spotify", ("spotify",)),),
            launcher=fail,
        )
        catalog.refresh()

        result = catalog.launch("Spotify")

        self.assertEqual(result["status"], "launch_failed")
        self.assertEqual(result["app"], {"id": "app_1", "label": "Spotify"})
        self.assertIn("Windows dijo que no", result["error"])

    def test_un_descubrimiento_roto_no_tumba_el_catalogo(self):
        def fail():
            raise OSError("registro ilegible")

        catalog = app_catalog.ApplicationCatalog(discover=fail, launcher=lambda _: None)

        catalog.refresh()

        self.assertTrue(catalog.snapshot.ready)
        self.assertEqual(catalog.snapshot.entries, ())
        self.assertEqual(catalog.snapshot.error, "registro ilegible")


class RefrescoEnSegundoPlano(TestCase):
    def test_arrancar_devuelve_sin_esperar_al_inventario_y_solo_crea_un_hilo(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def discover():
            calls.append(True)
            entered.set()
            release.wait(2)
            return ()

        catalog = app_catalog.ApplicationCatalog(discover=discover, launcher=lambda _: None)
        self.addCleanup(catalog.stop_background)

        catalog.start_background()
        self.assertTrue(entered.wait(1))
        catalog.start_background()
        self.assertEqual(calls, [True])
        release.set()

    def test_actualiza_periodicamente_sin_bloquear_lectores(self):
        refreshed_twice = threading.Event()
        calls = []

        def discover():
            calls.append(True)
            if len(calls) >= 2:
                refreshed_twice.set()
            return ()

        catalog = app_catalog.ApplicationCatalog(
            discover=discover,
            launcher=lambda _: None,
            refresh_interval=0.01,
        )
        self.addCleanup(catalog.stop_background)

        catalog.start_background()

        self.assertTrue(refreshed_twice.wait(1))


class ArranqueDelAgente(IsolatedAsyncioTestCase):
    async def test_el_cliente_inicia_el_catalogo_antes_de_conectar(self):
        config = NodeConfig(
            url="https://vibi.local",
            node_id="node-1",
            token="token",
            nombre="PC",
            projects_root=".",
        )
        with (
            patch.object(client.app_catalog.catalog, "start_background") as start,
            patch.object(client, "_sesion", AsyncMock(side_effect=asyncio.CancelledError)),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await client.run_forever(config)

        start.assert_called_once_with()


class LanzadorWindows(TestCase):
    def test_shortcut_se_abre_directamente_sin_shell(self):
        entry = _entry("app_1", "Spotify", ("spotify",), target=r"C:\\Spotify.lnk")

        with patch.object(app_catalog.os, "startfile", create=True) as startfile:
            app_catalog.launch_windows_entry(entry)

        startfile.assert_called_once_with(r"C:\\Spotify.lnk")

    def test_app_empaquetada_usa_argv_fijo(self):
        entry = _entry(
            "app_2",
            "Calculadora",
            ("calculadora",),
            kind="packaged",
            target="Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
        )

        with patch.object(app_catalog.subprocess, "Popen") as popen:
            app_catalog.launch_windows_entry(entry)

        # `sin_ventana()` aporta `creationflags` en Windows y nada fuera de él;
        # sin desempaquetarlo aquí, este test solo pasaba en las plataformas
        # donde no hace nada.
        popen.assert_called_once_with(
            [
                "explorer.exe",
                "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
            ],
            close_fds=True,
            **app_catalog.proceso.sin_ventana(),
        )

    def test_a_una_app_de_la_store_no_se_le_pasan_argumentos(self):
        """El shell de las apps empaquetadas no los admite, y hay que saberlo.

        Es el motivo de que WhatsApp y Spotify —las dos de la Store en esta
        máquina— no se puedan abrir escuchando: no es que no sean Chromium, es
        que no hay por dónde pasarles el flag.
        """
        entry = _entry(
            "app_2", "Spotify", ("spotify",),
            kind="packaged", target="SpotifyAB.SpotifyMusic_zpd!App",
        )

        with patch.object(app_catalog.subprocess, "Popen") as popen:
            app_catalog.launch_windows_entry(entry, ("--remote-debugging-port=9350",))

        argv = popen.call_args[0][0]
        self.assertNotIn("--remote-debugging-port=9350", argv)


class AbrirEscuchando(TestCase):
    """Una app de Chromium se abre lista para que se le hable por dentro.

    Cuesta un argumento, no cambia nada de cómo se ve, y es lo que permite
    después manejarla sin ponerle la ventana delante a nadie.
    """

    def test_a_discord_se_le_reserva_puerto_y_se_le_pasa_el_flag(self):
        from vibi_node import web_apps

        web_apps._agenda.clear()
        self.addCleanup(web_apps._agenda.clear)
        recibidos = []
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (_entry("app_1", "Discord", ("discord",)),),
            launcher=lambda entry, extra=(): recibidos.append(extra),
        )
        catalog.refresh()

        with patch("vibi_node.browser_mcp.escuchando", return_value=False):
            salida = catalog.launch("Discord")

        self.assertEqual(salida["status"], "launched")
        self.assertIn("puerto_web", salida)
        self.assertEqual(len(recibidos), 1)
        self.assertTrue(recibidos[0][0].startswith("--remote-debugging-port="))

    def test_a_lo_que_no_es_chromium_no_se_le_toca_nada(self):
        recibidos = []
        catalog = app_catalog.ApplicationCatalog(
            discover=lambda: (
                _entry("app_1", "Bloc de notas", ("bloc de notas",)),
            ),
            launcher=lambda entry, extra=(): recibidos.append(extra),
        )
        catalog.refresh()

        salida = catalog.launch("Bloc de notas")

        self.assertEqual(salida["status"], "launched")
        self.assertNotIn("puerto_web", salida)
        # Se lanza igual, pero sin un solo argumento añadido.
        self.assertEqual(recibidos, [()])


if __name__ == "__main__":
    import unittest

    unittest.main()

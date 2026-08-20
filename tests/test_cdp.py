"""Elegir la pestaña correcta, que es donde se decide si esto sirve o estorba.

Hablar con una pestaña por su protocolo de depuración es trivial: la parte
delicada es **cuál**. Un navegador tiene quince abiertas, y darle al play en la
que no era es exactamente el fallo que se venía a arreglar. La regla es la
misma que en el árbol de accesibilidad: ante la duda se pregunta, nunca se
elige por el usuario.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import cdp  # noqa: E402


def pagina(titulo, url="https://ejemplo.com", tipo="page"):
    return {
        "title": titulo,
        "url": url,
        "type": tipo,
        "webSocketDebuggerUrl": f"ws://127.0.0.1:9333/devtools/page/{titulo}",
    }


class ElegirPestana(TestCase):
    def test_con_una_sola_no_hace_falta_decir_cuál(self):
        elegida = cdp.elegir([pagina("Lo que sea")], None)
        self.assertEqual(elegida["title"], "Lo que sea")

    def test_con_varias_y_sin_pista_se_pregunta(self):
        with self.assertRaises(cdp.ErrorCDP) as caso:
            cdp.elegir([pagina("Una"), pagina("Otra")], None)

        # Y se enumeran, que es lo que permite contestar.
        self.assertIn("Una", str(caso.exception))
        self.assertIn("Otra", str(caso.exception))

    def test_por_un_trozo_del_título(self):
        elegida = cdp.elegir(
            [pagina("Home / X"), pagina("New Gen (Blue Lock) - YouTube")],
            "blue lock",
        )
        self.assertIn("Blue Lock", elegida["title"])

    def test_por_un_trozo_de_la_dirección(self):
        elegida = cdp.elegir(
            [
                pagina("Home / X", "https://x.com/home"),
                pagina("Vídeo", "https://www.youtube.com/watch?v=abc"),
            ],
            "youtube",
        )
        self.assertEqual(elegida["title"], "Vídeo")

    def test_el_título_exacto_gana_al_parecido(self):
        """«Vibi» no puede ser ambiguo por culpa de «Vibi — documentación»."""
        elegida = cdp.elegir(
            [pagina("Vibi"), pagina("Vibi — documentación")], "Vibi"
        )
        self.assertEqual(elegida["title"], "Vibi")

    def test_si_la_pista_casa_con_varias_se_pregunta(self):
        with self.assertRaises(cdp.ErrorCDP) as caso:
            cdp.elegir(
                [pagina("Blue Lock cap 1"), pagina("Blue Lock cap 2")],
                "blue lock",
            )

        self.assertIn("2 pestañas", str(caso.exception))

    def test_si_no_casa_ninguna_se_dice_lo_que_hay(self):
        with self.assertRaises(cdp.ErrorCDP) as caso:
            cdp.elegir([pagina("Home / X")], "spotify")

        self.assertIn("Home / X", str(caso.exception))

    def test_sin_pestañas_se_dice(self):
        with self.assertRaises(cdp.ErrorCDP):
            cdp.elegir([], "lo que sea")

    def test_los_acentos_y_las_mayúsculas_dan_igual(self):
        elegida = cdp.elegir([pagina("Vídeo de MÚSICA")], "video de musica")
        self.assertEqual(elegida["title"], "Vídeo de MÚSICA")

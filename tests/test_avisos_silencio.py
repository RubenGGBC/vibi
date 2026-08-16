"""Las reglas de silencio: qué notificaciones no llegan a decirse en voz alta.

La lista es negra y no blanca a propósito, y con datos: de las ocho
notificaciones acumuladas en un equipo de verdad, cuatro eran la misma promoción
repetida y ninguna era una persona escribiendo. Una lista blanca no ahorra nada
ahí, porque el problema no es qué aplicaciones escuchar sino que casi todo lo
que notifica Windows es publicidad.

Las reglas viven en el servidor y no en el nodo: son del usuario, y valen para
todos sus equipos a la vez.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import avisos_silencio as S  # noqa: E402


def _aviso(app="WhatsApp", titulo="Ana", cuerpo="¿Quedamos mañana?"):
    return {"app": app, "titulo": titulo, "cuerpo": cuerpo}


class Alcances(TestCase):
    """Una regla puede callar una aplicación entera o solo parte de ella."""

    def test_callar_una_aplicacion_entera(self):
        regla = S.Regla(app="NVIDIA App", patron="")
        self.assertTrue(S.silencia(regla, _aviso(app="NVIDIA App")))
        self.assertFalse(S.silencia(regla, _aviso(app="WhatsApp")))

    def test_callar_solo_lo_que_coincide_dentro_de_la_aplicacion(self):
        regla = S.Regla(app="Discord", patron="canal general")
        self.assertTrue(
            S.silencia(regla, _aviso(app="Discord", titulo="canal general"))
        )
        self.assertFalse(
            S.silencia(regla, _aviso(app="Discord", titulo="Ana"))
        )

    def test_el_patron_mira_titulo_y_cuerpo(self):
        regla = S.Regla(app="Discord", patron="ha entrado")
        self.assertTrue(
            S.silencia(regla, _aviso(app="Discord", titulo="sala",
                                     cuerpo="Pepe ha entrado"))
        )

    def test_da_igual_como_este_escrito(self):
        """Lo escribe un modelo a partir de lo que dijo una persona."""
        regla = S.Regla(app="nvidia app", patron="REWARD")
        self.assertTrue(
            S.silencia(regla, _aviso(app="NVIDIA App", titulo="New Reward Available"))
        )

    def test_las_tildes_no_deciden(self):
        regla = S.Regla(app="Correo", patron="promocion")
        self.assertTrue(
            S.silencia(regla, _aviso(app="Correo", titulo="Promoción del mes"))
        )

    def test_una_regla_sin_aplicacion_vale_para_todas(self):
        """«No me digas nada que hable de ofertas», venga de donde venga."""
        regla = S.Regla(app="", patron="oferta")
        self.assertTrue(S.silencia(regla, _aviso(app="Lo Que Sea", titulo="Oferta")))
        self.assertFalse(S.silencia(regla, _aviso(app="Lo Que Sea", titulo="Ana")))

    def test_una_regla_vacia_no_calla_el_mundo(self):
        """Un modelo que se equivoque no puede dejarte sordo de un golpe."""
        self.assertFalse(S.silencia(S.Regla(app="", patron=""), _aviso()))


class Filtrar(TestCase):
    def test_pasa_lo_que_ninguna_regla_calla(self):
        reglas = [S.Regla(app="NVIDIA App", patron="")]
        self.assertTrue(S.pasa(_aviso(), reglas))

    def test_no_pasa_lo_que_calla_alguna(self):
        reglas = [
            S.Regla(app="Xbox", patron=""),
            S.Regla(app="NVIDIA App", patron=""),
        ]
        self.assertFalse(S.pasa(_aviso(app="NVIDIA App"), reglas))

    def test_sin_reglas_pasa_todo(self):
        self.assertTrue(S.pasa(_aviso(app="Lo que sea"), []))


class ComoSeCuenta(TestCase):
    """Vibi dice en voz alta qué acaba de callar, para que puedas corregirla."""

    def test_una_aplicacion_entera(self):
        self.assertEqual(
            S.describir(S.Regla(app="Discord", patron="")),
            "No vuelvo a decirte nada de Discord.",
        )

    def test_parte_de_una_aplicacion(self):
        self.assertEqual(
            S.describir(S.Regla(app="Discord", patron="canal general")),
            "No vuelvo a decirte nada de Discord que hable de «canal general».",
        )

    def test_algo_venga_de_donde_venga(self):
        self.assertEqual(
            S.describir(S.Regla(app="", patron="oferta")),
            "No vuelvo a decirte nada que hable de «oferta», venga de donde venga.",
        )

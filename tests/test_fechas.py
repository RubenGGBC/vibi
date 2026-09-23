"""Las fechas de la pantalla, ya restadas contra hoy.

Todo se prueba contra un «hoy» fijo y no contra el de verdad: una prueba que
pase en septiembre y falle en enero no prueba nada, solo avisa tarde.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import fechas  # noqa: E402

HOY = date(2026, 9, 20)


class ComoSeEscribeUnaFecha(TestCase):
    """Los formatos que aparecen de verdad en una interfaz."""

    def test_dia_y_mes_en_espanol(self):
        self.assertEqual(fechas.primera("Concierto 13 oct", HOY), date(2026, 10, 13))
        self.assertEqual(
            fechas.primera("13 de octubre de 2026", HOY), date(2026, 10, 13)
        )

    def test_mes_y_dia_en_ingles(self):
        """Media máquina está en inglés aunque el sistema esté en español."""
        self.assertEqual(fechas.primera("Oct 13", HOY), date(2026, 10, 13))
        self.assertEqual(
            fechas.primera("October 13, 2026", HOY), date(2026, 10, 13)
        )

    def test_iso(self):
        self.assertEqual(fechas.primera("2026-10-13", HOY), date(2026, 10, 13))

    def test_con_barras_el_dia_va_primero(self):
        """Aquí no es como en el repositorio del que sale esto.

        Leer `13/10` al revés no da error, da una fecha válida once meses
        equivocada, que es el peor tipo de fallo que puede tener un parseo.
        """
        self.assertEqual(fechas.primera("13/10/2026", HOY), date(2026, 10, 13))
        self.assertEqual(fechas.primera("13/10/26", HOY), date(2026, 10, 13))

    def test_un_rango_se_queda_con_el_primer_dia(self):
        self.assertEqual(fechas.primera("13-15 oct", HOY), date(2026, 10, 13))

    def test_el_guion_tipografico_tambien(self):
        self.assertEqual(fechas.primera("13–15 oct", HOY), date(2026, 10, 13))


class CuandoNoHayAno(TestCase):
    def test_lo_que_queda_por_delante_es_de_este_ano(self):
        self.assertEqual(fechas.primera("31 dic", HOY), date(2026, 12, 31))

    def test_lo_que_queda_muy_atras_es_del_que_viene(self):
        """«15 feb» visto en septiembre no es de hace siete meses."""
        self.assertEqual(fechas.primera("15 feb", HOY), date(2027, 2, 15))

    def test_lo_que_queda_poco_atras_se_queda_donde_esta(self):
        """Un mes pasado sigue siendo pasado: una cita de la semana pasada."""
        self.assertEqual(fechas.primera("15 ago", HOY), date(2026, 8, 15))


class LoQueNoEsUnaFecha(TestCase):
    def test_un_texto_sin_fecha_no_inventa_ninguna(self):
        self.assertIsNone(fechas.primera("Guardar como", HOY))

    def test_un_dia_que_no_existe_no_es_una_fecha(self):
        self.assertIsNone(fechas.primera("32 de octubre", HOY))

    def test_un_mes_que_no_existe_tampoco(self):
        self.assertIsNone(fechas.primera("13/13/2026", HOY))

    def test_el_vacio_no_revienta(self):
        self.assertIsNone(fechas.primera("", HOY))
        self.assertIsNone(fechas.primera(None, HOY))


class ComoSeCuenta(TestCase):
    """Lo que se le da al modelo es la resta, no la fecha."""

    def test_hoy_manana_y_ayer_se_dicen_con_su_nombre(self):
        self.assertIn("hoy", fechas.contar(date(2026, 9, 20), HOY))
        self.assertIn("mañana", fechas.contar(date(2026, 9, 21), HOY))
        self.assertIn("ayer", fechas.contar(date(2026, 9, 19), HOY))

    def test_lo_de_mas_alla_va_en_dias(self):
        self.assertIn("dentro de 23 días", fechas.contar(date(2026, 10, 13), HOY))
        self.assertIn("hace 5 días", fechas.contar(date(2026, 9, 15), HOY))

    def test_la_fecha_tambien_va_escrita(self):
        """Para que el modelo pueda ordenar, no solo comparar con hoy."""
        self.assertIn("2026-10-13", fechas.contar(date(2026, 10, 13), HOY))


class Pista(TestCase):
    def test_sin_fecha_no_hay_pista(self):
        self.assertEqual(fechas.pista("botón Aceptar", HOY), "")

    def test_con_fecha_la_pista_lleva_la_resta_hecha(self):
        self.assertIn("dentro de 23 días", fechas.pista("Evento 13 oct", HOY))

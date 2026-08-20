"""Buscar archivos sin recorrerse el disco entero.

`files.search` recorría con `rglob` desde la raíz que le dieran. Medido en el
histórico de este equipo: **mediana de 300 segundos y 4 búsquedas caducadas de
14**. No es lento, es inservible — y se entiende, porque `rglob` entra en
`node_modules`, en `.git`, en `AppData` y en `$Recycle.Bin` con el mismo
entusiasmo que en la carpeta que te interesa.

Windows lleva un índice de todo eso desde hace veinte años. Medido el
20/08/2026 en esta máquina: **482 ms** para treinta PDF de todo el disco, contra
los 300 s del recorrido. Es la misma consulta que hace el cuadro de búsqueda del
explorador.

Lo que se prueba aquí es la lógica que rodea al índice, no el índice: cómo se
traduce lo que pide una persona a una consulta, y qué se hace cuando el índice
no está —una carpeta sin indexar, un Mac, un servicio parado—, porque entonces
hay que recorrer y ahí lo que salva es podar y ponerle reloj.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import buscador  # noqa: E402


class ComoSeTraduceLoQuePides(TestCase):
    def test_un_nombre_suelto_busca_por_contener(self):
        self.assertEqual(buscador.patron_a_like("factura"), "%factura%")

    def test_un_comodín_se_respeta_tal_cual(self):
        self.assertEqual(buscador.patron_a_like("*.pdf"), "%.pdf")
        self.assertEqual(buscador.patron_a_like("informe*"), "informe%")

    def test_los_comodines_de_sql_se_escapan(self):
        """Un `%` en el nombre del archivo es un `%`, no «cualquier cosa».

        Sin esto, buscar «50% descuento» le pide al índice todo lo que empiece
        por 50 y contenga descuento, que es medio disco.
        """
        salida = buscador.patron_a_like("50% descuento")
        self.assertEqual(salida, "%50[%] descuento%")

    def test_el_guión_bajo_también(self):
        self.assertEqual(buscador.patron_a_like("mi_archivo"), "%mi[_]archivo%")

    def test_una_comilla_no_puede_romper_la_consulta(self):
        salida = buscador.patron_a_like("O'Brien")
        self.assertNotIn("'", salida.replace("''", ""))


class LoQueNoSeRecorre(TestCase):
    """La poda, para cuando toca recorrer de verdad."""

    def test_se_salta_lo_que_nunca_te_interesa(self):
        for nombre in (
            "node_modules", ".git", "__pycache__", "$Recycle.Bin",
            ".venv", "AppData", "Windows",
        ):
            with self.subTest(nombre=nombre):
                self.assertTrue(buscador.se_salta(nombre), nombre)

    def test_no_se_salta_una_carpeta_normal(self):
        for nombre in ("Documentos", "morgana", "facturas 2026", "src"):
            with self.subTest(nombre=nombre):
                self.assertFalse(buscador.se_salta(nombre), nombre)

    def test_una_carpeta_oculta_cualquiera_se_salta(self):
        self.assertTrue(buscador.se_salta(".cache"))


class RecorrerConReloj(TestCase):
    """Sin índice se recorre, pero con tope: nunca más los 300 segundos."""

    def setUp(self):
        self.raiz = Path(__file__).resolve().parent.parent

    def test_encuentra_lo_que_hay(self):
        salida = buscador.por_recorrido("test_buscador.py", self.raiz, 10, 5.0)
        self.assertTrue(salida["resultados"])
        self.assertTrue(
            any(r["nombre"] == "test_buscador.py" for r in salida["resultados"])
        )

    def test_respeta_el_tope_de_resultados(self):
        salida = buscador.por_recorrido("*.py", self.raiz, 3, 5.0)
        self.assertEqual(len(salida["resultados"]), 3)
        self.assertTrue(salida["truncado"])

    def test_se_rinde_a_tiempo_y_lo_dice(self):
        inicio = time.monotonic()
        salida = buscador.por_recorrido(
            "no-existe-esto-*.zzz", self.raiz, 100, 0.3
        )
        transcurrido = time.monotonic() - inicio
        # Con margen para una vuelta larga del bucle, pero nada de 300 s.
        self.assertLess(transcurrido, 3.0)
        if salida["agotado"]:
            self.assertEqual(salida["resultados"], [])

    def test_no_se_mete_en_lo_podado(self):
        salida = buscador.por_recorrido("*.pyc", self.raiz, 5, 5.0)
        for encontrado in salida["resultados"]:
            self.assertNotIn("__pycache__", encontrado["ruta"])

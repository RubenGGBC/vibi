"""Qué modelos sabe usar agy, y cómo entender el comando `/model` del hilo.

`agy models` es un subcomando real de la CLI —lo confirmé ejecutándolo en esta
máquina— que le pregunta a Google y tarda sobre dos segundos. Por eso la lista
no vive hardcodeada aquí ni se llama a la CLI en cada prueba: lo que se prueba
es el descodificado de su salida y la interpretación del comando, que son
puras y no necesitan que `agy` esté instalado.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.executors import agy_modelos as M  # noqa: E402

# Captura real de `agy models` en esta máquina, el 2026-09-10.
SALIDA_REAL = """Fetching available models...
gemini-3.8-flash-high\tGemini 3.8 Flash (High)
gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)
gemini-3.8-flash-low\tGemini 3.8 Flash (Low)
gemini-3.1-pro-high\tGemini 3.1 Pro (High)
gemini-3.1-pro-low\tGemini 3.1 Pro (Low)
claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)
claude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)
gpt-oss-120b-medium\tGPT-OSS 120B (Medium)
"""


class DescodificarLaListaDeAgy(TestCase):
    def test_saca_el_id_y_la_etiqueta_de_cada_linea(self):
        modelos = M._parsear(SALIDA_REAL)

        self.assertEqual(modelos[0].id, "gemini-3.8-flash-high")
        self.assertEqual(modelos[0].etiqueta, "Gemini 3.8 Flash (High)")

    def test_la_linea_de_progreso_no_es_un_modelo(self):
        """«Fetching available models...» no lleva tabulador: no es una fila."""
        modelos = M._parsear(SALIDA_REAL)

        self.assertEqual(len(modelos), 8)


class SiElEffortVaEnElNombre(TestCase):
    """De los ocho, seis ya dicen su effort; dos no. Ahí cambia lo que se
    puede preguntar: a los primeros no se les puede mandar `--effort` —la
    propia CLI lo rechaza, `agy_process.py` ya sabe evitarlo—, y a los
    segundos sí se les puede añadir uno.
    """

    def test_un_modelo_con_sufijo_lleva_el_effort_en_el_nombre(self):
        modelo = M.Modelo(id="gemini-3.8-flash-high", etiqueta="x")

        self.assertTrue(modelo.effort_en_el_nombre)

    def test_un_modelo_sin_sufijo_no_lo_lleva(self):
        modelo = M.Modelo(id="claude-sonnet-4-6", etiqueta="x")

        self.assertFalse(modelo.effort_en_el_nombre)


def _modelos():
    return M._parsear(SALIDA_REAL)


class InterpretarElComando(TestCase):
    """El texto que escribe el usuario, ya decidido en algo que se puede hacer."""

    def test_model_solo_pide_la_lista(self):
        peticion = M.interpretar("/model", _modelos())

        self.assertEqual(peticion.tipo, "listar")

    def test_model_con_espacios_de_mas_tambien_pide_la_lista(self):
        peticion = M.interpretar("/model   ", _modelos())

        self.assertEqual(peticion.tipo, "listar")

    def test_default_vuelve_al_que_traiga_el_servidor(self):
        peticion = M.interpretar("/model default", _modelos())

        self.assertEqual(peticion.tipo, "por_defecto")

    def test_un_id_conocido_fija_ese_modelo(self):
        peticion = M.interpretar("/model gemini-3.8-flash-high", _modelos())

        self.assertEqual(peticion.tipo, "fijar")
        self.assertEqual(peticion.modelo.id, "gemini-3.8-flash-high")
        self.assertIsNone(peticion.effort)

    def test_un_id_desconocido_es_un_error_con_el_nombre_dentro(self):
        peticion = M.interpretar("/model gemini-inventado", _modelos())

        self.assertEqual(peticion.tipo, "error")
        self.assertIn("gemini-inventado", peticion.error)

    def test_un_modelo_sin_sufijo_acepta_effort_aparte(self):
        peticion = M.interpretar("/model claude-sonnet-4-6 high", _modelos())

        self.assertEqual(peticion.tipo, "fijar")
        self.assertEqual(peticion.modelo.id, "claude-sonnet-4-6")
        self.assertEqual(peticion.effort, "high")

    def test_un_modelo_con_sufijo_rechaza_effort_aparte(self):
        """La propia CLI lo rechaza al arrancar: mejor decirlo aquí que dejarlo
        fallar dos turnos después con un log críptico."""
        peticion = M.interpretar("/model gemini-3.8-flash-high low", _modelos())

        self.assertEqual(peticion.tipo, "error")
        self.assertIn("gemini-3.8-flash-high", peticion.error)

    def test_un_effort_que_no_es_ninguno_de_los_tres_es_un_error(self):
        peticion = M.interpretar("/model claude-sonnet-4-6 urgente", _modelos())

        self.assertEqual(peticion.tipo, "error")


class EsComando(TestCase):
    """Decide si el mensaje se intercepta antes de llegar a Claude o a agy."""

    def test_model_a_secas_es_comando(self):
        self.assertTrue(M.es_comando("/model"))

    def test_model_con_argumentos_es_comando(self):
        self.assertTrue(M.es_comando("/model default"))

    def test_un_mensaje_normal_no_es_comando(self):
        self.assertFalse(M.es_comando("¿qué modelo usas?"))

    def test_una_palabra_que_empieza_igual_no_es_el_comando(self):
        """`/modelfoo` no es `/model foo`: el prefijo tiene que cerrar en palabra."""
        self.assertFalse(M.es_comando("/modelfoo"))


class PedirleLaListaAAgy(TestCase):
    """`agy models` es una llamada de red real (~2 s medidos en esta máquina):
    aquí se sustituye por un doble y se prueba solo el envoltorio —qué
    binario se llama y cuándo se cachea—, no la CLI en sí.
    """

    def setUp(self):
        M._cache = None
        M._cache_en = 0.0

    def test_llama_al_binario_configurado_con_el_subcomando_models(self):
        with patch("app.executors.agy_modelos.subprocess.run") as ejecutar:
            ejecutar.return_value.stdout = SALIDA_REAL
            M.listar(binario="/ruta/a/agy")

        args = ejecutar.call_args.args[0]
        self.assertEqual(args, ["/ruta/a/agy", "models"])

    def test_una_segunda_llamada_no_repite_la_peticion(self):
        with patch("app.executors.agy_modelos.subprocess.run") as ejecutar:
            ejecutar.return_value.stdout = SALIDA_REAL
            M.listar(binario="/ruta/a/agy")
            M.listar(binario="/ruta/a/agy")

        self.assertEqual(ejecutar.call_count, 1)

    def test_un_fallo_de_agy_no_deja_la_lista_vacia_en_silencio(self):
        """Que `agy` no conteste no puede traducirse en «no hay modelos»: eso
        haría que /model listara vacío en vez de decir que algo falló."""
        with patch("app.executors.agy_modelos.subprocess.run", side_effect=OSError("no está")):
            with self.assertRaises(M.ErrorModelos):
                M.listar(binario="/ruta/a/agy")

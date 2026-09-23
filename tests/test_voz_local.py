"""Lo que el servicio de voz local hace con el texto y el audio, sin cargar el modelo."""
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:  # el entorno del core no lo trae; el de voz_local sí
    raise unittest.SkipTest("numpy solo está en el entorno de voz_local")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voz_local"))

import servidor  # noqa: E402


class PrepararElTexto(unittest.TestCase):
    def test_cada_frase_va_en_su_linea_para_que_kokoro_no_la_corte(self):
        self.assertEqual(
            servidor.preparar("Vale.  Ya está. ¿Algo más?"),
            "Vale.\nYa está.\n¿Algo más?",
        )

    def test_lo_que_lee_letra_a_letra_se_escribe_como_suena(self):
        self.assertEqual(servidor.preparar("Está en GitHub."), "Está en Guitjab.")
        self.assertEqual(servidor.preparar("haz un git pull"), "haz un guit pull")

    def test_no_toca_palabras_que_solo_lo_contienen(self):
        self.assertEqual(servidor.preparar("digital"), "digital")

    def test_las_horas_no_se_parten(self):
        self.assertEqual(servidor.preparar("A las 9:30 en punto."), "A las 9:30 en punto.")


class RecortarElSilencio(unittest.TestCase):
    def test_quita_los_extremos_y_deja_un_respiro(self):
        sr = 1000
        voz = np.ones(100, dtype=np.float32) * 0.5
        audio = np.concatenate([np.zeros(500), voz, np.zeros(800)]).astype(np.float32)

        recortado = servidor.recortar_silencio(audio, sr, margen_s=0.04)

        self.assertEqual(len(recortado), 100 + 40 + 40)

    def test_el_silencio_puro_se_deja_como_esta(self):
        audio = np.zeros(300, dtype=np.float32)

        self.assertEqual(len(servidor.recortar_silencio(audio, 1000)), 300)

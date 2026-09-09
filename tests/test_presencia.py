"""Cuándo se le puede dar un turno a agy sin quitárselo a nadie."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import presencia  # noqa: E402


class Libre(TestCase):
    def setUp(self):
        presencia.olvidar("u")
        self.addCleanup(presencia.olvidar, "u")

    def test_sin_saber_nada_esta_libre(self):
        """Un usuario que nunca ha abierto nada no bloquea sus propios avisos."""
        self.assertTrue(presencia.libre("u"))

    def test_la_cara_despierta_lo_ocupa(self):
        presencia.cara("u", True)
        self.assertFalse(presencia.libre("u"))
        self.assertIn("cara", presencia.por_que_ocupado("u"))

    def test_la_cara_dormida_no_lo_ocupa(self):
        presencia.cara("u", False)
        self.assertTrue(presencia.libre("u"))

    def test_el_hilo_recien_movido_lo_ocupa(self):
        presencia.chat_se_movio("u")
        self.assertFalse(presencia.libre("u"))
        self.assertIn("hilo", presencia.por_que_ocupado("u"))

    def test_el_hilo_quieto_el_tiempo_pedido_queda_libre(self):
        presencia.chat_se_movio("u")
        despues = presencia.time.monotonic() + presencia.CHAT_EN_REPOSO + 0.1
        with patch.object(presencia.time, "monotonic", return_value=despues):
            self.assertTrue(presencia.libre("u"))

    def test_una_cara_que_se_fue_sin_avisar_caduca(self):
        """Si el companion se cierra de golpe nadie manda el «ya no estoy».
        Sin caducidad los avisos no se contarían nunca más."""
        presencia.cara("u", True)
        despues = presencia.time.monotonic() + presencia.CARA_CADUCA + 1
        with patch.object(presencia.time, "monotonic", return_value=despues):
            self.assertTrue(presencia.libre("u"))

    def test_la_cara_manda_aunque_el_hilo_este_quieto(self):
        """Las dos condiciones son y, no o: hablando por voz no se interrumpe
        porque el hilo de texto lleve rato parado."""
        presencia.cara("u", True)
        despues = presencia.time.monotonic() + presencia.CHAT_EN_REPOSO + 0.1
        with patch.object(presencia.time, "monotonic", return_value=despues):
            self.assertFalse(presencia.libre("u"))

    def test_cada_usuario_va_por_su_cuenta(self):
        presencia.cara("u", True)
        self.addCleanup(presencia.olvidar, "otro")
        self.assertTrue(presencia.libre("otro"))

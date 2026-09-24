"""El teclado de macOS hablando con Quartz, sin pasar por `usecomputer`.

Quartz se sustituye por uno falso que apunta los eventos: lo que se prueba es
qué se postea y en qué orden, que es donde estaba el fallo de WhatsApp. Que la
tecla llegue a una aplicación de verdad no se puede probar sin tocar la
pantalla de quien ejecuta la suite.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import computer  # noqa: E402
from vibi_node import keyboard_macos as K  # noqa: E402


class QuartzFalso:
    """Lo justo de Quartz para ver qué eventos salen."""

    kCGEventSourceStateHIDSystemState = 1
    kCGHIDEventTap = 0

    def __init__(self, permiso: bool = True):
        self.permiso = permiso
        self.fuentes = []
        self.posteados = []

    def CGPreflightPostEventAccess(self):
        return self.permiso

    def CGEventSourceCreate(self, estado):
        fuente = SimpleNamespace(estado=estado)
        self.fuentes.append(fuente)
        return fuente

    def CGEventCreateKeyboardEvent(self, fuente, codigo, bajar):
        return SimpleNamespace(
            fuente=fuente, codigo=codigo, bajar=bajar, banderas=None, texto=None
        )

    def CGEventSetFlags(self, evento, banderas):
        evento.banderas = banderas

    def CGEventKeyboardSetUnicodeString(self, evento, unidades, texto):
        evento.texto = (unidades, texto)

    def CGEventPost(self, destino, evento):
        self.posteados.append(evento)


class ConQuartzFalso(TestCase):
    def setUp(self):
        self.quartz = QuartzFalso()
        for parche in (
            patch.object(K, "_quartz", side_effect=lambda: self.quartz),
            patch.object(K.time, "sleep"),
        ):
            parche.start()
            self.addCleanup(parche.stop)


class Pulsar(ConQuartzFalso):
    def test_el_intro_sale_con_fuente_y_separado(self):
        """Lo que `usecomputer` no hacía y WhatsApp descartaba."""
        K.pulsar("enter")

        abajo, arriba = self.quartz.posteados
        self.assertEqual((abajo.codigo, abajo.bajar), (0x24, True))
        self.assertEqual((arriba.codigo, arriba.bajar), (0x24, False))
        self.assertIsNotNone(abajo.fuente)
        self.assertEqual(
            abajo.fuente.estado, QuartzFalso.kCGEventSourceStateHIDSystemState
        )
        # Entre bajar y soltar hay espera, no van pegados.
        K.time.sleep.assert_any_call(K.ESPERA_TECLA)

    def test_return_e_intro_son_la_misma_tecla(self):
        for nombre in ("Return", "intro", "ENTER"):
            self.assertEqual(K.traducir(nombre), ((), 0x24))

    def test_una_combinacion_lleva_la_bandera_y_suelta_al_reves(self):
        K.pulsar("cmd+shift+t")

        codigos = [(e.codigo, e.bajar) for e in self.quartz.posteados]
        self.assertEqual(
            codigos,
            [
                (0x37, True), (0x38, True),
                (0x11, True), (0x11, False),
                (0x38, False), (0x37, False),
            ],
        )
        tecla = self.quartz.posteados[2]
        self.assertEqual(tecla.banderas, 0x100000 | 0x20000)
        # Al final no queda ningún modificador puesto.
        self.assertEqual(self.quartz.posteados[-1].banderas, 0)

    def test_repetir_postea_la_pareja_cada_vez(self):
        resultado = K.pulsar("down", 3)
        self.assertEqual(len(self.quartz.posteados), 6)
        self.assertEqual(resultado["veces"], 3)

    def test_una_tecla_desconocida_se_explica(self):
        with self.assertRaisesRegex(K.ErrorTeclado, "No sé qué tecla"):
            K.pulsar("hiperespacio")
        self.assertEqual(self.quartz.posteados, [])

    def test_sin_permiso_no_finge_que_ha_tecleado(self):
        """macOS tiraría los eventos en silencio y la orden volvería «ok»."""
        self.quartz.permiso = False
        with self.assertRaisesRegex(K.ErrorTeclado, "Accesibilidad"):
            K.pulsar("enter")
        self.assertEqual(self.quartz.posteados, [])


class Teclear(ConQuartzFalso):
    def test_el_texto_va_como_unicode_caracter_a_caracter(self):
        K.teclear("ñ@")

        textos = [e.texto for e in self.quartz.posteados]
        self.assertEqual(textos, [(1, "ñ"), (1, "ñ"), (1, "@"), (1, "@")])
        self.assertTrue(all(e.banderas == 0 for e in self.quartz.posteados))

    def test_un_emoji_cuenta_dos_unidades(self):
        K.teclear("🙂")
        self.assertEqual(self.quartz.posteados[0].texto, (2, "🙂"))

    def test_el_salto_de_linea_es_un_intro_de_verdad(self):
        K.teclear("a\r\nb")

        codigos = [
            (e.codigo, e.bajar) for e in self.quartz.posteados if e.texto is None
        ]
        self.assertEqual(codigos, [(0x24, True), (0x24, False)])

    def test_sin_texto_se_dice(self):
        with self.assertRaisesRegex(K.ErrorTeclado, "qué escribir"):
            K.teclear("")


class ElMacYaNoArrancaUsecomputer(TestCase):
    def test_en_mac_el_teclado_nativo_es_quartz(self):
        with patch.object(computer.platform, "system", return_value="Darwin"), \
             patch.object(K, "disponible", return_value=True):
            self.assertIs(computer._teclado_nativo(), K)

    def test_sin_pyobjc_vuelve_a_la_cli_en_vez_de_fallar(self):
        with patch.object(computer.platform, "system", return_value="Darwin"), \
             patch.object(K, "disponible", return_value=False):
            self.assertIsNone(computer._teclado_nativo())

    def test_su_error_llega_como_error_del_ordenador(self):
        teclado = MagicMock()
        teclado.ErrorTeclado = K.ErrorTeclado
        teclado.pulsar.side_effect = K.ErrorTeclado("sin permiso")
        with patch.object(computer, "_teclado_nativo", return_value=teclado), \
             patch.object(computer, "_ejecutar") as ejecutar, \
             self.assertRaisesRegex(computer.ErrorOrdenador, "sin permiso"):
            computer.pulsar("enter")
        ejecutar.assert_not_called()

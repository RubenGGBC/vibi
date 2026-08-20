"""Escribir en un campo cuando el camino principal se rompe.

Del turno real del 20/08/2026 a las 21:15, que es el que hay que tener en la
cabeza al leer esto. Vibi hizo **todo bien**: buscó «Ruffini» en WhatsApp,
encontró el chat, lo abrió, y localizó el campo correcto —el árbol lo describe
como `campo "Escribir un mensaje para Ruffini" (con foco)`—. Y ahí falló:

    escribir → No se pudo enfocar: (-2147220991, 'Un evento no pudo invocar
                a ninguno de los subscriptores')

`SetFocus()` revienta con ese COMError en WebView2. Y como `escribir` no tenía
más caminos, se rindió. El modelo, sin poder escribir, se puso a dar clics
durante tres minutos y acabó abriendo Outlook y la Store.

Dos cosas de ese error, y las dos son ridículas de puro obvias una vez vistas:

1. **El campo ya tenía el foco.** Lo decía el propio árbol. Pedir foco a algo
   que ya lo tiene no puede ser lo que impida escribir.
2. **`SetFocus` no es la única puerta.** `LegacyIAccessible` —la interfaz vieja
   de accesibilidad— también pone texto, y la implementan controles que no
   publican `Value`.

Un fallo en el último paso de una cadena de quince cuesta la cadena entera. Por
eso aquí se agotan las vías antes de rendirse.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import ui_windows  # noqa: E402


class ElementoFalso:
    """Un control de UIA de mentira, con las averías que se han visto."""

    def __init__(
        self,
        nombre="Escribir un mensaje",
        con_foco=False,
        valor=None,          # None = no publica ValuePattern
        valor_pega=True,     # si SetValue tiene efecto de verdad
        legacy=False,        # si publica LegacyIAccessible
        setfocus_revienta=False,
    ):
        self.CurrentName = nombre
        self._con_foco = con_foco
        self._valor = valor
        self._valor_pega = valor_pega
        self._legacy = legacy
        self._setfocus_revienta = setfocus_revienta
        self.escrito_por = []

    def SetFocus(self):
        if self._setfocus_revienta:
            raise OSError(
                -2147220991,
                "Un evento no pudo invocar a ninguno de los subscriptores",
            )
        self._con_foco = True

    def GetCurrentPropertyValue(self, propiedad):
        if propiedad == ui_windows.P_FOCO:
            return self._con_foco
        return None

    def GetCachedPropertyValue(self, propiedad):
        if propiedad == ui_windows.P_FOCO:
            return self._con_foco
        return None

    # --- patrones ---
    def GetCurrentPattern(self, identificador):
        if identificador == ui_windows.PATRON_VALOR and self._valor is not None:
            return _Valor(self)
        if identificador == ui_windows.PATRON_ANTIGUO and self._legacy:
            return _Legacy(self)
        return None


class _Patron:
    def __init__(self, duenio):
        self.duenio = duenio

    def QueryInterface(self, _interfaz):
        return self


class _Valor(_Patron):
    CurrentIsReadOnly = False

    @property
    def CurrentValue(self):
        return self.duenio._valor

    def SetValue(self, texto):
        self.duenio.escrito_por.append(("valor", texto))
        if self.duenio._valor_pega:
            self.duenio._valor = texto


class _Legacy(_Patron):
    def SetValue(self, texto):
        self.duenio.escrito_por.append(("legacy", texto))
        self.duenio._valor = texto

    def DoDefaultAction(self):
        pass


class Base(TestCase):
    def setUp(self):
        # `_gen()` devuelve los interfaces generados por comtypes; a los falsos
        # les da igual cuáles sean, solo hace falta que exista el atributo.
        class Interfaces:
            def __getattr__(self, _nombre):
                return object

        parche = patch.object(ui_windows, "_gen", return_value=Interfaces())
        parche.start()
        self.addCleanup(parche.stop)
        self.teclado = patch("vibi_node.computer.teclear").start()
        self.addCleanup(patch.stopall)


class CuandoElFocoRevienta(Base):
    """El caso de WhatsApp, exacto."""

    def test_si_el_campo_ya_tiene_el_foco_no_se_le_pide(self):
        campo = ElementoFalso(con_foco=True, setfocus_revienta=True)

        via = ui_windows.escribir(campo, "hola")

        self.assertIn("teclado", via)
        self.teclado.assert_called_once_with("hola")

    def test_sin_foco_y_con_setfocus_roto_se_prueba_la_interfaz_vieja(self):
        campo = ElementoFalso(setfocus_revienta=True, legacy=True)

        via = ui_windows.escribir(campo, "hola")

        self.assertIn("antigua", via)
        self.assertEqual(campo.escrito_por, [("legacy", "hola")])

    def test_si_no_queda_ninguna_vía_se_dice_qué_ha_pasado(self):
        campo = ElementoFalso(setfocus_revienta=True)

        with self.assertRaises(ui_windows.ErrorUI) as caso:
            ui_windows.escribir(campo, "hola")

        mensaje = str(caso.exception).lower()
        self.assertIn("escribir un mensaje", mensaje)
        # Y tiene que sugerir la salida, o el modelo se pone a dar clics.
        self.assertTrue("navegador" in mensaje or "web" in mensaje, mensaje)


class CuandoElValorNoPega(Base):
    """La otra avería de WhatsApp: acepta el texto y no lo pone."""

    def test_se_cae_a_la_interfaz_vieja_antes_de_rendirse(self):
        campo = ElementoFalso(valor="", valor_pega=False, legacy=True)

        via = ui_windows.escribir(campo, "hola")

        self.assertIn("antigua", via)
        self.assertEqual(
            campo.escrito_por, [("valor", "hola"), ("legacy", "hola")]
        )


class ElCaminoNormalNoCambia(Base):
    def test_un_campo_que_funciona_se_escribe_por_valor(self):
        campo = ElementoFalso(valor="")

        via = ui_windows.escribir(campo, "hola")

        self.assertEqual(via, "patrón valor")
        self.assertEqual(campo._valor, "hola")

    def test_un_campo_sin_patrones_se_teclea_como_siempre(self):
        campo = ElementoFalso()

        via = ui_windows.escribir(campo, "hola")

        self.assertIn("teclado", via)
        self.teclado.assert_called_once_with("hola")

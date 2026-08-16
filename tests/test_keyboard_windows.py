"""El teclado de Windows hablando con `SendInput`, sin pasar por Node.

Lo que se prueba aquí es la traducción: de «ctrl+shift+t» a los códigos que
entiende Windows, y de un texto cualquiera a pulsaciones. Que la tecla llegue a
la ventana lo prueba `test_ui_windows_real`, que sí toca una aplicación.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

if platform.system() == "Windows":
    from vibi_node import keyboard_windows as K  # noqa: E402
else:  # pragma: no cover - depende del sistema
    K = None


@skipUnless(platform.system() == "Windows", "SendInput solo existe en Windows")
class TraducirCombinaciones(TestCase):
    def test_una_tecla_suelta(self):
        self.assertEqual(K.traducir("enter"), ((), K.VK_TECLAS["enter"]))
        self.assertEqual(K.traducir("f5"), ((), K.VK_TECLAS["f5"]))

    def test_una_combinacion_separa_modificadores_de_la_tecla(self):
        modificadores, tecla = K.traducir("ctrl+s")
        self.assertEqual(modificadores, (K.MODIFICADORES["ctrl"],))
        self.assertEqual(tecla, ord("S"))

    def test_varios_modificadores_en_orden(self):
        modificadores, tecla = K.traducir("ctrl+shift+t")
        self.assertEqual(
            modificadores, (K.MODIFICADORES["ctrl"], K.MODIFICADORES["shift"])
        )
        self.assertEqual(tecla, ord("T"))

    def test_da_igual_como_lo_escriba_el_modelo(self):
        esperado = K.traducir("ctrl+s")
        for forma in ("CTRL+S", " ctrl + s ", "Control+s", "ctrl-s"):
            with self.subTest(forma=forma):
                self.assertEqual(K.traducir(forma), esperado)

    def test_el_vocabulario_prometido_al_modelo_existe_entero(self):
        """Lo que `devices.key` dice que acepta tiene que funcionar."""
        for tecla in ("enter", "tab", "escape", "backspace", "up", "f5",
                      "ctrl+s", "alt+tab", "ctrl+shift+t", "down", "left",
                      "right", "space", "delete", "home", "end", "pageup",
                      "pagedown", "esc", "intro", "supr", "arriba", "abajo"):
            with self.subTest(tecla=tecla):
                K.traducir(tecla)

    def test_una_tecla_que_no_existe_lo_dice(self):
        with self.assertRaises(K.ErrorTeclado) as caso:
            K.traducir("tecla_de_la_suerte")
        self.assertIn("tecla_de_la_suerte", str(caso.exception))

    def test_una_combinacion_sin_tecla_final_lo_dice(self):
        with self.assertRaises(K.ErrorTeclado):
            K.traducir("ctrl+")


@skipUnless(platform.system() == "Windows", "SendInput solo existe en Windows")
class Pulsar(TestCase):
    def test_una_combinacion_suelta_los_modificadores_al_reves(self):
        """Bajar ctrl, bajar shift, bajar T, soltar T, soltar shift, soltar ctrl.

        Soltar en el mismo orden que se bajó deja el modificador pulsado
        mientras la tecla ya subió, y hay aplicaciones que ven eso como un
        atajo distinto.
        """
        with patch.object(K, "_enviar") as enviar:
            K.pulsar("ctrl+shift+t")
        entradas = enviar.call_args[0]
        self.assertEqual(len(entradas), 6)
        codigos = [e.ki.wVk for e in entradas]
        soltadas = [bool(e.ki.dwFlags & K.KEYEVENTF_KEYUP) for e in entradas]
        self.assertEqual(
            codigos,
            [K.MODIFICADORES["ctrl"], K.MODIFICADORES["shift"], ord("T"),
             ord("T"), K.MODIFICADORES["shift"], K.MODIFICADORES["ctrl"]],
        )
        self.assertEqual(soltadas, [False, False, False, True, True, True])

    def test_una_tecla_sola_son_dos_eventos(self):
        with patch.object(K, "_enviar") as enviar:
            K.pulsar("enter")
        entradas = enviar.call_args[0]
        self.assertEqual(len(entradas), 2)
        self.assertEqual([e.ki.wVk for e in entradas],
                         [K.VK_TECLAS["enter"]] * 2)

    def test_repetir_manda_la_tecla_varias_veces(self):
        with patch.object(K, "_enviar") as enviar:
            resultado = K.pulsar("down", 4)
        self.assertEqual(enviar.call_count, 4)
        self.assertEqual(resultado["veces"], 4)


@skipUnless(platform.system() == "Windows", "SendInput solo existe en Windows")
class Teclear(TestCase):
    def test_cada_caracter_va_por_unicode_y_no_por_codigo_de_tecla(self):
        """Así no depende de la distribución del teclado del usuario.

        Con códigos de tecla, una «ñ» o un «@» salen distintos en un teclado
        español y en uno inglés. Con `KEYEVENTF_UNICODE` se manda el carácter.
        """
        with patch.object(K, "_enviar") as enviar:
            K.teclear("añ@")
        entradas = enviar.call_args[0]
        self.assertEqual(len(entradas), 6, "dos eventos por carácter")
        for entrada in entradas:
            self.assertTrue(entrada.ki.dwFlags & K.KEYEVENTF_UNICODE)
            self.assertEqual(entrada.ki.wVk, 0)
        self.assertEqual([e.ki.wScan for e in entradas[::2]],
                         [ord("a"), ord("ñ"), ord("@")])

    def test_un_salto_de_linea_es_intro_de_verdad(self):
        """`KEYEVENTF_UNICODE` con \\n no hace nada en casi ninguna ventana."""
        with patch.object(K, "_enviar") as enviar:
            K.teclear("a\nb")
        codigos = [e.ki.wVk for e in enviar.call_args[0]]
        self.assertIn(K.VK_TECLAS["enter"], codigos)

    def test_un_texto_largo_no_se_parte_ni_tiene_tope(self):
        """El tope de 32.767 caracteres era de la línea de comandos."""
        largo = "x" * 50_000
        with patch.object(K, "_enviar") as enviar:
            resultado = K.teclear(largo)
        self.assertEqual(resultado["caracteres"], 50_000)
        self.assertGreaterEqual(enviar.call_count, 1)

    def test_texto_vacio_lo_dice(self):
        with self.assertRaises(K.ErrorTeclado):
            K.teclear("")

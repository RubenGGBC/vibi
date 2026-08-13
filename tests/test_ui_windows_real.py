"""El árbol de accesibilidad contra ventanas de verdad, en Windows.

Lo único que no puede decir un test con backend de mentira: si UIA contesta,
cuánto tarda y si un clic por patrón mueve la aplicación de verdad. Se salta
solo en cualquier máquina sin GUI o sin `comtypes`, así que no rompe el resto
de la suite.

Se usa la Calculadora porque viene en toda instalación de Windows, no guarda
nada y se cierra sin preguntar. **Todo se pulsa por patrón de UIA y nunca por
el teclado global**: un test que teclease acabaría escribiendo en la ventana
que tuviera el foco, que en la máquina de alguien es su editor.
"""
from __future__ import annotations

import platform
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

if platform.system() != "Windows":  # pragma: no cover - depende del sistema
    raise unittest.SkipTest("El árbol de UIA solo existe en Windows")

from vibi_node import ui, ui_tree  # noqa: E402

# Los botones que hacen falta, en los idiomas en los que sabemos llamarlos. Si
# el sistema está en otro, el test se salta en vez de fallar: lo que se prueba
# es la mecánica, no la traducción de Windows.
BOTONES = {
    "siete": ("Siete", "Seven"),
    "por": ("Multiplicar por", "Multiply by"),
    "seis": ("Seis", "Six"),
    "igual": ("Es igual a", "Equals"),
}

CALCULADORA = ("Calculadora", "Calculator")


def _hay_backend() -> bool:
    try:
        return ui.disponible()
    except Exception:
        return False


@unittest.skipUnless(_hay_backend(), "Falta comtypes o no hay sesión gráfica")
class ArbolReal(TestCase):
    proceso = None
    titulo = None

    @classmethod
    def setUpClass(cls):
        subprocess.run(["cmd", "/c", "start", "", "calc"], check=False)
        # La Calculadora arranca un proceso y deja que otro pinte la ventana,
        # así que se espera a verla y no a que el comando vuelva.
        limite = time.monotonic() + 20
        while time.monotonic() < limite:
            for ventana in _ventanas():
                if any(n in ventana for n in CALCULADORA):
                    cls.titulo = ventana
                    time.sleep(1.0)
                    return
            time.sleep(0.5)
        raise unittest.SkipTest("La Calculadora no llegó a abrirse")

    @classmethod
    def tearDownClass(cls):
        subprocess.run(
            ["taskkill", "/IM", "CalculatorApp.exe", "/F"],
            check=False, capture_output=True,
        )
        subprocess.run(
            ["taskkill", "/IM", "Calculator.exe", "/F"],
            check=False, capture_output=True,
        )

    def setUp(self):
        ui.olvidar()

    # --- mirar ---

    def test_la_ventana_trae_sus_controles_con_nombre(self):
        vista = ui.capturar(self.titulo)

        self.assertFalse(vista["vacio"])
        self.assertGreater(vista["nodos"], 20)
        self.assertIn("botón", vista["arbol"])

    def test_mirar_una_ventana_baja_del_segundo(self):
        """Si tarda más que una captura, el árbol no tiene razón de existir."""
        ui.capturar(self.titulo)  # la primera paga el arranque de comtypes

        vista = ui.capturar(self.titulo)

        self.assertLess(vista["ms"], 1000, f"tardó {vista['ms']} ms")

    def test_la_poda_deja_el_arbol_en_algo_que_cabe(self):
        vista = ui.capturar(self.titulo)

        self.assertLessEqual(vista["nodos"], ui_tree.MAX_NODOS)
        self.assertGreater(vista["omitidos"], 0)

    def test_una_ventana_que_no_existe_se_dice_con_las_que_si(self):
        with self.assertRaises(ui.ErrorUI) as caso:
            ui.capturar("Ventana Que No Existe En Ningún Sitio")

        self.assertIn("Abiertas:", str(caso.exception))

    # --- actuar ---

    def _nombre_de(self, arbol: str, clave: str) -> str:
        for candidato in BOTONES[clave]:
            if f'"{candidato}"' in arbol:
                return candidato
        raise unittest.SkipTest(
            f"La Calculadora de esta máquina no llama «{BOTONES[clave][0]}» "
            "a ese botón; probablemente está en otro idioma."
        )

    def test_un_lote_opera_la_calculadora_en_una_sola_llamada(self):
        arbol = ui.capturar(self.titulo)["arbol"]
        pasos = [
            {"accion": "clic", "buscar": {"nombre": self._nombre_de(arbol, c)}}
            for c in ("siete", "por", "seis", "igual")
        ]

        resultado = ui.ejecutar_lote(pasos, ventana=self.titulo)

        self.assertIsNone(resultado["error"], resultado["pasos"])
        self.assertEqual(resultado["completados"], 4)
        # 7 x 6, y la comprobación es el propio árbol que devuelve el lote.
        self.assertIn("42", resultado["arbol"])

    def test_el_lote_pulsa_por_patron_y_no_con_el_raton(self):
        arbol = ui.capturar(self.titulo)["arbol"]

        resultado = ui.ejecutar_lote(
            [{"accion": "clic", "buscar": {"nombre": self._nombre_de(arbol, "siete")}}],
            ventana=self.titulo,
        )

        self.assertIn("patrón", resultado["pasos"][0]["via"])

    def test_un_ref_de_la_lectura_anterior_sirve_para_pulsar(self):
        vista = ui.capturar(self.titulo)
        nombre = self._nombre_de(vista["arbol"], "siete")
        ref = next(
            linea.split("]")[0].strip("[")
            for linea in vista["arbol"].splitlines()
            if f'"{nombre}"' in linea
        )

        resultado = ui.ejecutar_lote(
            [{"accion": "clic", "ref": ref}], ventana=self.titulo
        )

        self.assertIsNone(resultado["error"], resultado["pasos"])

    def test_un_ref_inventado_no_pulsa_nada(self):
        ui.capturar(self.titulo)

        resultado = ui.ejecutar_lote(
            [{"accion": "clic", "ref": "e9999"}], ventana=self.titulo
        )

        self.assertEqual(resultado["error"], "ref_desconocido")

    def test_lo_que_no_esta_se_dice_en_vez_de_pulsar_otra_cosa(self):
        resultado = ui.ejecutar_lote(
            [{"accion": "clic", "buscar": {"nombre": "Botón Inexistente XYZ"}}],
            ventana=self.titulo,
        )

        self.assertEqual(resultado["error"], "no_encontrado")
        self.assertEqual(resultado["completados"], 0)


def _ventanas() -> list[str]:
    from vibi_node import ui_windows

    try:
        return [v.titulo for v in ui_windows.ventanas()]
    except Exception:
        return []

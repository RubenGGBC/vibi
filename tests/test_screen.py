"""Fotografiar la pantalla: elegir cuál, medirla y devolver el mapa.

La parte que se prueba con monitores de mentira es la que no depende del
sistema: qué monitor sale elegido para cada palabra y qué números salen en el
detalle, que son los que después traducen un punto de la imagen a un punto del
escritorio. La captura de verdad va al final y se salta fuera de Windows.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import screen  # noqa: E402

# Dos monitores de 1920x1080 uno al lado del otro, con el principal a la
# derecha: es la disposición de este equipo y la que rompe las cuentas ingenuas,
# porque el de la izquierda vive en coordenadas negativas.
DOS_PANTALLAS = [
    {
        "numero": 1, "x": 0, "y": 0, "ancho": 1920, "alto": 1080,
        "principal": True, "con_cursor": False,
    },
    {
        "numero": 2, "x": -1920, "y": 0, "ancho": 1920, "alto": 1080,
        "principal": False, "con_cursor": True,
    },
]


class ElegirPantalla(TestCase):
    """`_elegir` es común a Windows y macOS: se prueba una vez."""

    def test_cada_palabra_saca_el_monitor_que_toca(self):
        casos = {
            "principal": 1,
            "cursor": 2,
            "secundaria": 2,
            "izquierda": 2,
            "derecha": 1,
            "n1": 1,
            "n2": 2,
        }
        for selector, numero in casos.items():
            with self.subTest(selector=selector):
                elegida = screen._elegir(DOS_PANTALLAS, selector)
                self.assertEqual(elegida["numero"], numero)

    def test_todas_no_elige_ninguna(self):
        self.assertIsNone(screen._elegir(DOS_PANTALLAS, "todas"))

    def test_sin_cursor_en_ningun_monitor_cae_en_la_principal(self):
        # El ratón entre dos monitores no está en ninguno de los rectángulos.
        sueltas = [{**p, "con_cursor": False} for p in DOS_PANTALLAS]
        self.assertEqual(screen._elegir(sueltas, "cursor")["numero"], 1)

    def test_pedir_una_pantalla_que_no_existe_lo_dice(self):
        una = [DOS_PANTALLAS[0]]
        with self.assertRaises(screen.ErrorPantalla) as caso:
            screen._elegir(una, "n2")
        self.assertIn("solo tiene 1", str(caso.exception))

        with self.assertRaises(screen.ErrorPantalla):
            screen._elegir(una, "secundaria")


@skipUnless(platform.system() == "Windows", "la geometría es de Windows")
class GeometriaDeWindows(TestCase):
    def test_describe_los_monitores_como_los_espera_elegir(self):
        pantallas = screen._pantallas_windows()
        self.assertTrue(pantallas, "este equipo tiene al menos una pantalla")

        for pantalla in pantallas:
            self.assertEqual(
                set(pantalla),
                {"numero", "x", "y", "ancho", "alto", "principal", "con_cursor"},
            )
            self.assertGreater(pantalla["ancho"], 0)
            self.assertGreater(pantalla["alto"], 0)

        # Numeradas de 1 a N y sin saltos: el modelo dice «la 2» contando así.
        self.assertEqual(
            [p["numero"] for p in pantallas],
            list(range(1, len(pantallas) + 1)),
        )
        # Windows pone siempre la principal en el origen del escritorio virtual.
        principales = [p for p in pantallas if p["principal"]]
        self.assertEqual(len(principales), 1)
        self.assertEqual((principales[0]["x"], principales[0]["y"]), (0, 0))
        # El cursor está como mucho en una.
        self.assertLessEqual(len([p for p in pantallas if p["con_cursor"]]), 1)


class DetalleDeLaCaptura(TestCase):
    """Los números que salen del detalle, con la foto simulada.

    Importa porque de aquí sale el mapa: `origen_x`/`origen_y` son los que
    permiten volver de un punto de la imagen a un punto del escritorio, y con un
    monitor en negativo equivocarse ahí manda el clic a la otra pantalla.
    """

    def _capturar(self, selector: str, destino: Path, tamano=(1568, 882)):
        """`tamano` es lo que devuelve la foto: el tamaño ya reducido."""
        with patch.object(screen, "_pantallas_windows", return_value=DOS_PANTALLAS), \
             patch.object(screen, "_fotografiar", return_value=tamano) as foto:
            detalle = screen._capturar_windows(selector, destino)
        return detalle, foto

    def test_un_monitor_concreto_lleva_su_origen(self):
        detalle, foto = self._capturar("izquierda", Path("x.jpg"))
        self.assertEqual(detalle["numero"], 2)
        self.assertEqual((detalle["origen_x"], detalle["origen_y"]), (-1920, 0))
        self.assertEqual((detalle["ancho_real"], detalle["alto_real"]), (1920, 1080))
        self.assertEqual(detalle["pantallas"], 2)
        self.assertEqual(detalle["pantalla"], "pantalla 2")
        # Se le pidió a la foto exactamente ese rectángulo.
        region = foto.call_args[0][0]
        self.assertEqual(region, (-1920, 0, 1920, 1080))

    def test_la_principal_se_dice_que_es_la_principal(self):
        detalle, _ = self._capturar("principal", Path("x.jpg"))
        self.assertEqual(detalle["pantalla"], "pantalla 1 (principal)")

    def test_todas_cubre_el_escritorio_virtual_entero(self):
        detalle, foto = self._capturar("todas", Path("x.jpg"), tamano=(1568, 441))
        self.assertEqual(detalle["numero"], 0)
        self.assertEqual(detalle["pantalla"], "todas las pantallas")
        self.assertEqual((detalle["origen_x"], detalle["origen_y"]), (-1920, 0))
        self.assertEqual((detalle["ancho_real"], detalle["alto_real"]), (3840, 1080))
        self.assertEqual(foto.call_args[0][0], (-1920, 0, 3840, 1080))

    def test_el_detalle_arma_un_mapa_que_computer_sabe_leer(self):
        screen.olvidar_mapa()
        self.addCleanup(screen.olvidar_mapa)
        detalle, _ = self._capturar("izquierda", Path("x.jpg"))
        self.assertEqual(
            screen._recordar_mapa(detalle), "-1920,0,1920,1080,1568,882"
        )


class ReducirLaImagen(TestCase):
    """El lado largo se recorta a 1568 px y la proporción se respeta."""

    def test_un_4k_apaisado_baja_por_el_ancho(self):
        self.assertEqual(screen._medida_reducida(3840, 2160), (1568, 882))

    def test_un_monitor_vertical_baja_por_el_alto(self):
        self.assertEqual(screen._medida_reducida(1080, 1920), (882, 1568))

    def test_lo_que_ya_cabe_no_se_toca(self):
        self.assertEqual(screen._medida_reducida(1280, 720), (1280, 720))

    def test_nunca_sale_un_lado_de_cero(self):
        ancho, alto = screen._medida_reducida(4000, 1)
        self.assertGreaterEqual(alto, 1)


@skipUnless(platform.system() == "Windows", "captura de verdad, solo Windows")
class CapturaDeVerdad(TestCase):
    """Una foto real: lo único que no puede decir un test con dobles."""

    def test_fotografia_la_principal_y_devuelve_un_jpeg(self):
        try:
            resultado = screen.capturar("la principal")
        except screen.ErrorPantalla as error:
            self.skipTest(f"esta máquina no puede capturar: {error}")

        imagen, detalle = resultado["jpeg"], resultado["detalle"]
        self.assertTrue(imagen.startswith(b"\xff\xd8"), "es un JPEG")
        self.assertGreater(len(imagen), 1024)
        self.assertLessEqual(max(detalle["ancho"], detalle["alto"]), screen.LADO_MAXIMO)
        self.assertEqual(detalle["bytes"], len(imagen))
        # Y deja el mapa puesto para que se pueda tocar lo que se acaba de ver.
        self.assertTrue(screen.mapa_actual())

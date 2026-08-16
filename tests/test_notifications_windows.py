"""Leer las notificaciones que Windows enseña, y quedarse solo con las nuevas.

Lo que se prueba con dobles es lo que no depende del sistema: quedarse con lo
recién llegado, juntar el título y el cuerpo, y aguantar una notificación a la
que le falta la mitad de los datos —que es la mayoría, en cuanto sales de las
aplicaciones bien hechas—. La lectura de verdad va al final y se salta sola si
esta máquina no da permiso.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

if platform.system() == "Windows":
    from vibi_node import notifications_windows as N
else:  # pragma: no cover - depende del sistema
    N = None


def _aviso(id_, app="WhatsApp", titulo="Ana", cuerpo="¿Quedamos mañana?"):
    return N.Aviso(id=id_, app=app, titulo=titulo, cuerpo=cuerpo, cuando="")


@skipUnless(platform.system() == "Windows", "las notificaciones son de Windows")
class QuedarseConLasNuevas(TestCase):
    """El centro de notificaciones devuelve todo lo acumulado en cada sondeo.

    Sin memoria de lo ya visto, Vibi te leería el mismo mensaje cada segundo.
    """

    def setUp(self):
        self.vigia = N.Vigia()

    def test_la_primera_vez_no_dice_nada(self):
        """Al arrancar hay notificaciones viejas en el centro; no son noticia.

        Si al encender el agente te leyera las ocho que llevan ahí desde ayer,
        lo apagarías el primer día.
        """
        nuevas = self.vigia.novedades([_aviso(1), _aviso(2)])
        self.assertEqual(nuevas, [])

    def test_despues_solo_las_que_no_estaban(self):
        self.vigia.novedades([_aviso(1), _aviso(2)])
        nuevas = self.vigia.novedades([_aviso(1), _aviso(2), _aviso(3)])
        self.assertEqual([a.id for a in nuevas], [3])

    def test_lo_mismo_repetido_no_vuelve_a_saltar(self):
        self.vigia.novedades([_aviso(1)])
        self.vigia.novedades([_aviso(1), _aviso(2)])
        self.assertEqual(self.vigia.novedades([_aviso(1), _aviso(2)]), [])

    def test_una_que_desaparece_y_vuelve_no_es_nueva(self):
        """Descartar una notificación y que la app la reponga con el mismo id."""
        self.vigia.novedades([_aviso(1), _aviso(2)])
        self.vigia.novedades([_aviso(1)])            # la 2 se descartó
        self.assertEqual(self.vigia.novedades([_aviso(1), _aviso(2)]), [])

    def test_la_memoria_no_crece_sin_fin(self):
        """Un equipo encendido semanas no puede acumular ids para siempre."""
        for tanda in range(0, N.MAX_VISTAS * 3, 10):
            self.vigia.novedades([_aviso(i) for i in range(tanda, tanda + 10)])
        self.assertLessEqual(len(self.vigia._vistas), N.MAX_VISTAS)

    def test_lo_viejo_olvidado_no_resucita_lo_reciente(self):
        """Al podar se tira lo antiguo, no lo último que acaba de pasar."""
        for tanda in range(0, N.MAX_VISTAS * 2, 10):
            self.vigia.novedades([_aviso(i) for i in range(tanda, tanda + 10)])
        ultimo = N.MAX_VISTAS * 2 - 1
        self.assertEqual(self.vigia.novedades([_aviso(ultimo)]), [])


@skipUnless(platform.system() == "Windows", "las notificaciones son de Windows")
class LeerElTexto(TestCase):
    """Windows entrega los textos sueltos y sin decir cuál es cuál."""

    def test_el_primer_texto_es_el_titulo_y_el_resto_el_cuerpo(self):
        aviso = N._componer(7, "WhatsApp", ["Ana", "¿Quedamos mañana?"], "")
        self.assertEqual(aviso.titulo, "Ana")
        self.assertEqual(aviso.cuerpo, "¿Quedamos mañana?")

    def test_varios_parrafos_se_juntan_en_el_cuerpo(self):
        aviso = N._componer(7, "Xbox", ["Grounded 2", "Baja al abismo.", "Gratis."], "")
        self.assertEqual(aviso.cuerpo, "Baja al abismo. Gratis.")

    def test_una_sola_linea_es_titulo_sin_cuerpo(self):
        aviso = N._componer(7, "Xbox", ["Actualización disponible"], "")
        self.assertEqual(aviso.titulo, "Actualización disponible")
        self.assertEqual(aviso.cuerpo, "")

    def test_sin_texto_no_revienta(self):
        aviso = N._componer(7, "Algo", [], "")
        self.assertEqual((aviso.titulo, aviso.cuerpo), ("", ""))

    def test_los_espacios_de_sobra_se_van(self):
        aviso = N._componer(7, "X", ["  Ana  ", "  hola\n\n  "], "")
        self.assertEqual((aviso.titulo, aviso.cuerpo), ("Ana", "hola"))

    def test_sin_aplicacion_se_dice_que_no_se_sabe(self):
        self.assertEqual(N._componer(7, "", ["hola"], "").app, "desconocida")


@skipUnless(platform.system() == "Windows", "las notificaciones son de Windows")
class Disponibilidad(TestCase):
    def test_sin_el_paquete_no_esta_disponible_y_no_revienta(self):
        with patch.object(N, "_api", side_effect=N.ErrorNotificaciones("no hay")):
            self.assertFalse(N.disponible())


@skipUnless(platform.system() == "Windows", "las notificaciones son de Windows")
class DesdeUnHiloConCOMdeUIA(TestCase):
    """Leer notificaciones desde el hilo que ya usó el árbol de accesibilidad.

    No es rebuscado: `ui_windows` deja el hilo en apartamento de un solo hilo al
    preparar UIA, las órdenes del nodo se atienden desde donde toque, y ahí la
    espera bloqueante de WinRT está prohibida. Se coló en la suite entera
    pasando en aislado, que es la peor forma de encontrarlo.
    """

    def test_no_revienta_por_el_apartamento_de_com(self):
        if not N.disponible():
            self.skipTest("esta máquina no da permiso para leer notificaciones")
        from vibi_node import ui_windows

        if not ui_windows.disponible():
            self.skipTest("esta máquina no tiene UIA")
        ui_windows._automation()  # deja este hilo en STA
        avisos = N.leer()  # antes: «Cannot call blocking method from STA»
        self.assertIsInstance(avisos, list)


@skipUnless(platform.system() == "Windows", "las notificaciones son de Windows")
class LecturaDeVerdad(TestCase):
    """Contra el centro de notificaciones real de esta máquina."""

    def test_se_leen_las_que_haya(self):
        if not N.disponible():
            self.skipTest("esta máquina no da permiso para leer notificaciones")
        avisos = N.leer()
        self.assertIsInstance(avisos, list)
        for aviso in avisos:
            self.assertIsInstance(aviso.id, int)
            self.assertIsInstance(aviso.app, str)
            self.assertTrue(aviso.app, "siempre hay nombre de aplicación")

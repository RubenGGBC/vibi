"""Qué encuentra el instalador en la máquina y qué le deja hacer al usuario.

Lo que se prueba aquí es la decisión, no el hallazgo: que un requisito que falta
bloquee o no según lo imprescindible que sea, y que una capacidad se ofrezca
solo donde funciona de verdad. Prometer control de escritorio en un Linux es
peor que no ofrecerlo: el usuario lo activa, y falla el día que lo necesita.
"""
import unittest
from unittest.mock import patch

from installer import deteccion


class ElSistemaSeMiraAntesDeOfrecerNada(unittest.TestCase):
    def test_reconoce_los_tres_sistemas(self):
        for crudo, esperado in (
            ("Windows", "windows"),
            ("Darwin", "macos"),
            ("Linux", "linux"),
        ):
            with patch("platform.system", return_value=crudo):
                self.assertEqual(deteccion.sistema_operativo(), esperado)

    def test_un_sistema_desconocido_no_se_disfraza_de_linux(self):
        """Adivinar aquí sale caro: decidiría capacidades por una suposición."""
        with patch("platform.system", return_value="FreeBSD"):
            self.assertEqual(deteccion.sistema_operativo(), "desconocido")


class LaVersionDeWindowsSeLeeDelBuild(unittest.TestCase):
    """`platform.release()` dice «10» en Windows 11, y no es un detalle.

    Es lo primero que lee el usuario en la pantalla —«va a vivir en tu
    Windows 10»— y equivocarse ahí hace dudar de todo lo demás. Python no lo
    arregla: lo que distingue las dos es el número de compilación, y 22000 es
    la frontera que fijó Microsoft.
    """

    def test_un_build_moderno_es_windows_once(self):
        with patch("platform.system", return_value="Windows"), patch(
            "platform.release", return_value="10"
        ), patch("platform.version", return_value="10.0.26200"):
            self.assertIn("11", deteccion.descripcion_del_sistema())

    def test_un_build_viejo_sigue_siendo_windows_diez(self):
        with patch("platform.system", return_value="Windows"), patch(
            "platform.release", return_value="10"
        ), patch("platform.version", return_value="10.0.19045"):
            self.assertIn("10", deteccion.descripcion_del_sistema())

    def test_fuera_de_windows_no_se_toca_nada(self):
        with patch("platform.system", return_value="Linux"), patch(
            "platform.release", return_value="6.8.0"
        ):
            self.assertEqual(deteccion.descripcion_del_sistema(), "Linux 6.8.0")


class LasCapacidadesDependenDeDondeInstalas(unittest.TestCase):
    def _claves(self, so):
        return {c.clave: c for c in deteccion.capacidades(so)}

    def test_en_windows_esta_todo(self):
        capacidades = self._claves("windows")

        self.assertTrue(capacidades["escritorio"].disponible)
        self.assertTrue(capacidades["notificaciones"].disponible)
        self.assertTrue(capacidades["wake_word"].disponible)

    def test_en_linux_el_escritorio_no_se_ofrece_y_dice_por_que(self):
        capacidades = self._claves("linux")

        escritorio = capacidades["escritorio"]
        self.assertFalse(escritorio.disponible)
        # Sin motivo, el usuario solo ve una casilla apagada y no sabe si es
        # culpa suya, si le falta algo o si es que ahí no existe.
        self.assertTrue(escritorio.motivo)

    def test_lo_que_no_depende_del_sistema_se_ofrece_en_todos(self):
        """El chat y la malla son el producto: si eso no va, no hay Vibi."""
        for so in ("windows", "macos", "linux"):
            capacidades = self._claves(so)
            self.assertTrue(capacidades["chat"].disponible, so)
            self.assertTrue(capacidades["malla"].disponible, so)

    def test_toda_capacidad_explica_para_que_sirve(self):
        """Es una pantalla de opciones, no una lista de módulos."""
        for capacidad in deteccion.capacidades("windows"):
            self.assertTrue(capacidad.explicacion, capacidad.clave)
            self.assertNotIn("_", capacidad.nombre, capacidad.clave)


class LosRequisitosDistinguenLoQueBloqueaDeLoQueLimita(unittest.TestCase):
    def _requisito(self, clave, **cambios):
        base = {
            "clave": clave,
            "nombre": clave,
            "encontrado": True,
            "detalle": "",
            "imprescindible": False,
            "como_conseguirlo": "",
        }
        base.update(cambios)
        return deteccion.Requisito(**base)

    def test_sin_lo_imprescindible_no_se_puede_instalar(self):
        faltan = (
            self._requisito("python", encontrado=True, imprescindible=True),
            self._requisito("agy", encontrado=False, imprescindible=True),
        )

        self.assertFalse(deteccion.se_puede_instalar(faltan))

    def test_lo_opcional_que_falte_no_bloquea(self):
        """Sin `npx` no hay navegador, pero Vibi conversa y toca el disco."""
        requisitos = (
            self._requisito("python", encontrado=True, imprescindible=True),
            self._requisito("npx", encontrado=False, imprescindible=False),
        )

        self.assertTrue(deteccion.se_puede_instalar(requisitos))

    def test_lo_que_falta_dice_como_conseguirlo(self):
        """Un instalador que solo dice «falta agy» deja al usuario buscando."""
        for requisito in deteccion.requisitos():
            if not requisito.encontrado:
                self.assertTrue(
                    requisito.como_conseguirlo, f"{requisito.clave} sin remedio"
                )


class ElPythonQueCorreElInstaladorTieneQueValer(unittest.TestCase):
    def test_una_version_vieja_se_detecta_como_ausente(self):
        with patch.object(deteccion.sys, "version_info", (3, 9, 0)):
            requisito = deteccion.requisito_python()

        self.assertFalse(requisito.encontrado)
        self.assertIn("3.11", requisito.como_conseguirlo)

    def test_la_version_actual_vale(self):
        with patch.object(deteccion.sys, "version_info", (3, 12, 1)):
            self.assertTrue(deteccion.requisito_python().encontrado)


if __name__ == "__main__":
    unittest.main()

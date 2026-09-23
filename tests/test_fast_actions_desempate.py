"""Abrir la que era cuando el catálogo no sabe cuál de las tres querías.

En esta máquina Discord sale tres veces y hay dos «chrome» de verdad. Lo que
antes salía de ahí era una pregunta —«he encontrado X, Y y Z, ¿cuál quieres?»—
para alguien que solo quería abrir algo. Esto prueba cuándo se puede contestar
esa pregunta sin molestar, y sobre todo cuándo no.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import fast_actions  # noqa: E402

USUARIO = {"id": "u-1"}

CANDIDATAS = [
    {"id": "chrome-google", "label": "Google Chrome"},
    {"id": "chrome-helium", "label": "Helium"},
]


def respuesta(status, **extra):
    return {
        "state": "ok",
        "node_dispatch_ms": 12,
        "result": {"status": status, "node_execution_ms": 3, **extra},
    }


def abierta(label="Google Chrome"):
    return respuesta("launched", app={"id": "chrome-google", "label": label})


class Ayudas:
    """Los parches que comparten los dos casos, sin ser un caso ella misma.

    Va como mixin y no como `TestCase` padre a propósito: heredar de un caso
    vuelve a ejecutar sus pruebas dentro del hijo, y entonces la suite dice
    que se han probado cosas que solo se han probado una vez.
    """

    def setUp(self):
        self.disponible = patch.object(
            fast_actions.decisor, "disponible", return_value=True
        )
        self.disponible.start()
        self.addCleanup(self.disponible.stop)

    def lanzando(self, *resultados):
        return patch.object(fast_actions, "_lanzar", AsyncMock(side_effect=resultados))

    def eligiendo(self, elegida):
        return patch.object(
            fast_actions.decisor, "desempatar", AsyncMock(return_value=elegida)
        )


class Desempate(Ayudas, IsolatedAsyncioTestCase):
    """Lo que hace el desempate cuando el catálogo deja varias."""

    async def test_ambigua_que_se_resuelve_se_abre_sin_preguntar(self):
        with self.lanzando(respuesta("ambiguous", candidates=CANDIDATAS), abierta()):
            with self.eligiendo("chrome-google"):
                desenlace = await fast_actions.execute_fast_action(
                    USUARIO, fast_actions.LaunchAction("chrome", "abre el chrome")
                )

        self.assertTrue(desenlace.handled)
        self.assertEqual(desenlace.status, "launched")
        self.assertIn("Google Chrome", desenlace.response)

    async def test_se_abre_por_el_id_de_la_elegida_y_no_por_lo_que_se_escribio(self):
        """El id casa exacto: preguntar dos veces por «chrome» sería un bucle."""
        lanzar = AsyncMock(
            side_effect=[respuesta("ambiguous", candidates=CANDIDATAS), abierta()]
        )
        with patch.object(fast_actions, "_lanzar", lanzar):
            with self.eligiendo("chrome-helium"):
                await fast_actions.execute_fast_action(
                    USUARIO, fast_actions.LaunchAction("chrome", "abre el chrome")
                )

        self.assertEqual(lanzar.await_args_list[1].args[1], "chrome-helium")

    async def test_si_no_lo_tiene_claro_se_pregunta_como_siempre(self):
        with self.lanzando(respuesta("ambiguous", candidates=CANDIDATAS)):
            with self.eligiendo(None):
                desenlace = await fast_actions.execute_fast_action(
                    USUARIO, fast_actions.LaunchAction("chrome", "abre el chrome")
                )

        self.assertEqual(desenlace.status, "ambiguous")
        self.assertIn("¿Cuál quieres?", desenlace.response)

    async def test_sin_decisor_el_camino_es_exactamente_el_de_antes(self):
        self.disponible.stop()
        self.addCleanup(self.disponible.start)
        with patch.object(
            fast_actions.decisor, "disponible", return_value=False
        ):
            with self.lanzando(respuesta("ambiguous", candidates=CANDIDATAS)):
                with patch.object(
                    fast_actions.decisor, "desempatar", AsyncMock()
                ) as preguntado:
                    desenlace = await fast_actions.execute_fast_action(
                        USUARIO, fast_actions.LaunchAction("chrome", "abre chrome")
                    )

        preguntado.assert_not_awaited()
        self.assertEqual(desenlace.status, "ambiguous")

    async def test_el_despacho_de_los_dos_intentos_se_cuenta_entero(self):
        """Esconder lo que cuesta el atajo sería esconder cuándo no compensa."""
        with self.lanzando(respuesta("ambiguous", candidates=CANDIDATAS), abierta()):
            with self.eligiendo("chrome-google"):
                desenlace = await fast_actions.execute_fast_action(
                    USUARIO, fast_actions.LaunchAction("chrome", "abre chrome")
                )

        self.assertEqual(desenlace.node_dispatch_ms, 24)

    async def test_si_la_elegida_tampoco_se_abre_se_cuenta_lo_del_primer_intento(self):
        with self.lanzando(
            respuesta("ambiguous", candidates=CANDIDATAS),
            respuesta("not_found", candidates=[]),
        ):
            with self.eligiendo("chrome-google"):
                desenlace = await fast_actions.execute_fast_action(
                    USUARIO, fast_actions.LaunchAction("chrome", "abre chrome")
                )

        self.assertEqual(desenlace.status, "ambiguous")


class CoincidenciaParcial(Ayudas, IsolatedAsyncioTestCase):
    """`not_found` con parciales: ahí puede que no esté la buena."""

    async def test_se_le_ofrece_decir_que_ninguna(self):
        """Nunca se abstiene: sin esa opción escrita, elegiría igual."""
        desempatar = AsyncMock(return_value=None)
        with self.lanzando(respuesta("not_found", candidates=CANDIDATAS)):
            with patch.object(fast_actions.decisor, "desempatar", desempatar):
                await fast_actions.execute_fast_action(
                    USUARIO, fast_actions.LaunchAction("chrom", "abre chrom")
                )

        opciones = desempatar.await_args.args[2]
        self.assertIn(fast_actions.NINGUNA, opciones)

    async def test_si_dice_que_ninguna_no_se_abre_nada(self):
        with self.lanzando(respuesta("not_found", candidates=CANDIDATAS)):
            with self.eligiendo(fast_actions.NINGUNA):
                desenlace = await fast_actions.execute_fast_action(
                    USUARIO, fast_actions.LaunchAction("chrom", "abre chrom")
                )

        self.assertFalse(desenlace.handled)
        self.assertEqual(desenlace.status, "not_found")

    async def test_se_le_exige_mas_seguridad_que_a_una_ambigua(self):
        desempatar = AsyncMock(return_value=None)
        with self.lanzando(respuesta("not_found", candidates=CANDIDATAS)):
            with patch.object(fast_actions.decisor, "desempatar", desempatar):
                await fast_actions.execute_fast_action(
                    USUARIO, fast_actions.LaunchAction("chrom", "abre chrom")
                )

        self.assertEqual(
            desempatar.await_args.args[3], fast_actions.UMBRAL_PARCIAL
        )
        self.assertGreater(fast_actions.UMBRAL_PARCIAL, fast_actions.decisor.UMBRAL)

    async def test_una_parcial_resuelta_se_ahorra_el_turno_del_motor(self):
        with self.lanzando(
            respuesta("not_found", candidates=CANDIDATAS), abierta("Helium")
        ):
            with self.eligiendo("chrome-helium"):
                desenlace = await fast_actions.execute_fast_action(
                    USUARIO, fast_actions.LaunchAction("helio", "abre helio")
                )

        self.assertTrue(desenlace.handled)
        self.assertIn("Helium", desenlace.response)


class LoQuePreguntaElDesempate(IsolatedAsyncioTestCase):
    async def test_va_la_frase_entera_y_no_solo_el_nombre_recortado(self):
        """«abre el chrome del trabajo» y «abre el chrome» no se resuelven igual."""
        desempatar = AsyncMock(return_value=None)
        with patch.object(fast_actions.decisor, "disponible", return_value=True):
            with patch.object(
                fast_actions,
                "_lanzar",
                AsyncMock(return_value=respuesta("ambiguous", candidates=CANDIDATAS)),
            ):
                with patch.object(fast_actions.decisor, "desempatar", desempatar):
                    await fast_actions.execute_fast_action(
                        USUARIO,
                        fast_actions.LaunchAction("chrome", "abre el chrome del trabajo"),
                    )

        estado = desempatar.await_args.args[0]
        self.assertEqual(estado["lo_que_pidio"], "abre el chrome del trabajo")

    async def test_lo_que_se_escribio_se_guarda_al_reconocer_la_orden(self):
        accion = fast_actions.recognize_launch("abre el chrome del trabajo")

        self.assertEqual(accion.app, "chrome del trabajo")
        self.assertEqual(accion.texto, "abre el chrome del trabajo")


class Candidatas(IsolatedAsyncioTestCase):
    """Lo que se le ofrece al modelo sale de lo que manda el nodo."""

    def test_se_leen_el_id_y_la_etiqueta(self):
        self.assertEqual(
            fast_actions._opciones_de(CANDIDATAS),
            {"chrome-google": "Google Chrome", "chrome-helium": "Helium"},
        )

    def test_lo_que_no_tiene_las_dos_cosas_no_es_una_opcion(self):
        """Una opción que no se sabe describir es una que nadie puede elegir."""
        self.assertEqual(
            fast_actions._opciones_de(
                [{"id": "x"}, {"label": "Y"}, "ni siquiera un diccionario"]
            ),
            {},
        )

    def test_lo_que_no_es_una_lista_no_revienta(self):
        self.assertEqual(fast_actions._opciones_de(None), {})

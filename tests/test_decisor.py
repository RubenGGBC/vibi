"""El desempate: quién elige cuando el árbol deja varios candidatos.

Sin red. Lo que se prueba es la disciplina —cuándo se pregunta, cuándo se
acepta la respuesta y qué pasa cuando no hay respuesta—, no si Jev acierta.
Eso último solo lo puede decir la API, y no se llama desde una prueba.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import decisor  # noqa: E402

OPCIONES = {
    "e1": 'botón "Aceptar" (en "Guardar cambios")',
    "e2": 'botón "Aceptar" (en "Borrar todo")',
}


class RespuestaFalsa:
    def __init__(self, cuerpo):
        self._cuerpo = json.dumps(cuerpo).encode()

    def read(self):
        return self._cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def contestando(eleccion, confianza):
    return RespuestaFalsa({
        "answers": {
            "cual": {
                "type": "choice",
                "choice": eleccion,
                "confidence": confianza,
            }
        }
    })


class ConKey(TestCase):
    def setUp(self):
        parche = patch.dict("os.environ", {"OPPER_API_KEY": "op-de-mentira"})
        parche.start()
        self.addCleanup(parche.stop)


class Disponibilidad(TestCase):
    def test_sin_key_no_hay_quien_desempate(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(decisor.disponible())

    def test_con_key_si(self):
        with patch.dict("os.environ", {"OPPER_API_KEY": "op-x"}):
            self.assertTrue(decisor.disponible())


class Desempate(ConKey):
    def test_devuelve_la_eleccion_cuando_va_seguro(self):
        respuesta = contestando("e2", 0.94)
        with patch("urllib.request.urlopen", return_value=respuesta):
            elegido = decisor.desempatar("ventana", "¿cuál?", OPCIONES)

        self.assertEqual(elegido, "e2")

    def test_por_debajo_del_umbral_no_elige(self):
        """Jev siempre contesta algo: la confianza es el único freno."""
        respuesta = contestando("e1", 0.51)
        with patch("urllib.request.urlopen", return_value=respuesta):
            elegido = decisor.desempatar("ventana", "¿cuál?", OPCIONES)

        self.assertIsNone(elegido)

    def test_justo_en_el_umbral_vale(self):
        respuesta = contestando("e1", 0.80)
        with patch("urllib.request.urlopen", return_value=respuesta):
            self.assertEqual(
                decisor.desempatar("ventana", "¿cuál?", OPCIONES), "e1"
            )

    def test_una_eleccion_que_no_estaba_en_la_lista_no_vale(self):
        respuesta = contestando("e9", 1.0)
        with patch("urllib.request.urlopen", return_value=respuesta):
            self.assertIsNone(decisor.desempatar("ventana", "¿?", OPCIONES))

    def test_un_fallo_de_red_deja_el_lote_como_estaba(self):
        """Quedarse sin internet no puede convertirse en un clic al azar."""
        with patch("urllib.request.urlopen", side_effect=OSError("sin red")):
            self.assertIsNone(decisor.desempatar("ventana", "¿?", OPCIONES))

    def test_sin_key_ni_se_pregunta(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("urllib.request.urlopen") as llamada:
                self.assertIsNone(decisor.desempatar("v", "¿?", OPCIONES))

        llamada.assert_not_called()

    def test_con_un_solo_candidato_no_se_gasta_una_llamada(self):
        with patch("urllib.request.urlopen") as llamada:
            self.assertIsNone(decisor.desempatar("v", "¿?", {"e1": "botón"}))

        llamada.assert_not_called()


class Peticion(ConKey):
    def cuerpo_enviado(self):
        with patch(
            "urllib.request.urlopen", return_value=contestando("e1", 0.9)
        ) as llamada:
            decisor.desempatar("el árbol", "¿cuál pulsar?", OPCIONES)
        return json.loads(llamada.call_args[0][0].data)

    def test_el_estado_y_las_opciones_van_donde_jev_los_espera(self):
        cuerpo = self.cuerpo_enviado()

        self.assertEqual(cuerpo["state"], "el árbol")
        pregunta = cuerpo["questions"]["cual"]
        self.assertEqual(pregunta["type"], "choice")
        self.assertEqual(pregunta["criteria"], OPCIONES)

    def test_la_key_viaja_en_la_cabecera(self):
        with patch(
            "urllib.request.urlopen", return_value=contestando("e1", 0.9)
        ) as llamada:
            decisor.desempatar("v", "¿?", OPCIONES)

        peticion = llamada.call_args[0][0]
        self.assertEqual(
            peticion.get_header("Authorization"), "Bearer op-de-mentira"
        )


# ---------- Varias preguntas en una sola petición ----------

def contestando_varias(respuestas):
    return RespuestaFalsa({"answers": respuestas})


class VariasPreguntas(ConKey):
    """La idea que más rinde: el estado se manda una vez.

    Partir una decisión en preguntas independientes cuesta lo mismo que una
    sola, y evita que el ruido de una contamine a la otra.
    """

    PREGUNTAS = {
        "ruta": decisor.eleccion("¿qué hago?", {"a": "una", "b": "otra"}),
        "ok": decisor.juicio("¿salió bien?"),
    }

    def test_las_dos_vuelven_de_una_sola_llamada(self):
        respuesta = contestando_varias({
            "ruta": {"choice": "b", "confidence": 0.9},
            "ok": {"noul": 0.7},
        })
        with patch("urllib.request.urlopen", return_value=respuesta) as llamada:
            contestado = decisor.preguntar("estado", self.PREGUNTAS)

        self.assertEqual(llamada.call_count, 1)
        self.assertEqual(contestado.eleccion("ruta").opcion, "b")
        self.assertAlmostEqual(contestado.juicio("ok").probabilidad, 0.7)

    def test_si_falta_una_respuesta_no_vale_ninguna(self):
        """Media respuesta es peor que ninguna: se decidiría a medias."""
        respuesta = contestando_varias({"ruta": {"choice": "a", "confidence": 0.9}})
        with patch("urllib.request.urlopen", return_value=respuesta):
            self.assertIsNone(decisor.preguntar("estado", self.PREGUNTAS))

    def test_un_estado_que_no_es_texto_viaja_como_json(self):
        """Datos sueltos se leen mejor con sus nombres puestos."""
        respuesta = contestando_varias({"ruta": {"choice": "a", "confidence": 0.9}})
        with patch("urllib.request.urlopen", return_value=respuesta) as llamada:
            decisor.preguntar(
                {"pidio": "abre discord"},
                {"ruta": decisor.eleccion("¿?", {"a": "una", "b": "otra"})},
            )

        cuerpo = json.loads(llamada.call_args[0][0].data)
        self.assertEqual(json.loads(cuerpo["state"]), {"pidio": "abre discord"})

    def test_sin_preguntas_ni_se_llama(self):
        with patch("urllib.request.urlopen") as llamada:
            self.assertIsNone(decisor.preguntar("estado", {}))

        llamada.assert_not_called()


class Reparto(ConKey):
    """Dos opciones a 0,45 y 0,44 son un empate disfrazado de decisión."""

    def test_el_reparto_llega_cuando_la_api_lo_manda(self):
        respuesta = contestando_varias({
            "cual": {
                "choice": "e1",
                "confidence": 0.46,
                "probabilities": {"e1": 0.46, "e2": 0.44},
            }
        })
        with patch("urllib.request.urlopen", return_value=respuesta):
            contestado = decisor.preguntar(
                "v", {"cual": decisor.eleccion("¿?", OPCIONES)}
            )

        self.assertEqual(contestado.eleccion("cual").reparto["e2"], 0.44)

    def test_sin_reparto_la_eleccion_sigue_valiendo(self):
        """No todas las respuestas lo traen, y no es motivo para tirarla."""
        respuesta = contestando("e1", 0.95)
        with patch("urllib.request.urlopen", return_value=respuesta):
            contestado = decisor.preguntar(
                "v", {"cual": decisor.eleccion("¿?", OPCIONES)}
            )

        self.assertEqual(contestado.eleccion("cual").reparto, {})


class Comprobar(ConKey):
    """El juicio de sí o no: comprobar lo que ya se hizo, no autorizarlo."""

    def test_por_encima_del_medio_es_que_si(self):
        with patch(
            "urllib.request.urlopen",
            return_value=contestando_varias({"ok": {"noul": 0.8}}),
        ):
            self.assertIs(decisor.comprobar("estado", "¿entró el texto?"), True)

    def test_por_debajo_es_que_no(self):
        with patch(
            "urllib.request.urlopen",
            return_value=contestando_varias({"ok": {"noul": 0.2}}),
        ):
            self.assertIs(decisor.comprobar("estado", "¿entró el texto?"), False)

    def test_sin_red_no_dice_ni_si_ni_no(self):
        """`None` no es «no»: es que aquí no hay quien lo diga."""
        with patch("urllib.request.urlopen", side_effect=OSError("sin red")):
            self.assertIsNone(decisor.comprobar("estado", "¿entró?"))


class Registro(ConKey):
    """Un desempate que sale mal es invisible desde fuera."""

    def setUp(self):
        super().setUp()
        decisor.olvidar()
        self.addCleanup(decisor.olvidar)

    def test_queda_apuntado_lo_ultimo_que_se_juzgo(self):
        with patch(
            "urllib.request.urlopen", return_value=contestando("e2", 0.94)
        ):
            decisor.desempatar("ventana", "¿cuál?", OPCIONES)

        ultimo = decisor.ultimo()
        self.assertEqual(ultimo["respuestas"]["cual"]["opcion"], "e2")
        self.assertGreaterEqual(ultimo["ms"], 0)

    def test_lo_que_no_se_pudo_juzgar_no_se_apunta(self):
        with patch("urllib.request.urlopen", side_effect=OSError("sin red")):
            decisor.desempatar("ventana", "¿cuál?", OPCIONES)

        self.assertIsNone(decisor.ultimo())

"""Del aviso que manda el nodo a la frase que Vibi dice en voz alta."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import avisos  # noqa: E402
from app import avisos_silencio as S  # noqa: E402


def _crudo(app="WhatsApp", titulo="Ana", cuerpo="¿Quedamos mañana a las cinco?"):
    return {"id": 1, "app": app, "titulo": titulo, "cuerpo": cuerpo, "cuando": ""}


class Saneado(TestCase):
    """Un nodo comprometido no puede mandar lo que quiera."""

    def test_un_aviso_normal_pasa_entero(self):
        limpio = avisos.sanear(_crudo())
        self.assertEqual(limpio["app"], "WhatsApp")
        self.assertEqual(limpio["titulo"], "Ana")

    def test_lo_larguisimo_se_recorta(self):
        limpio = avisos.sanear(_crudo(cuerpo="x" * 10_000))
        self.assertLessEqual(len(limpio["cuerpo"]), avisos.MAX_TEXTO)

    def test_sin_nada_util_no_hay_aviso(self):
        self.assertIsNone(avisos.sanear({"app": "", "titulo": "", "cuerpo": ""}))
        self.assertIsNone(avisos.sanear("no soy un diccionario"))

    def test_los_saltos_de_linea_no_sobreviven(self):
        """Va a acabar en una frase hablada; los párrafos no pintan nada."""
        limpio = avisos.sanear(_crudo(cuerpo="una\nlinea\n\notra"))
        self.assertEqual(limpio["cuerpo"], "una linea otra")


class SinModelo(TestCase):
    """Si el modelo no contesta, el aviso llega igual.

    Enunciar es mejorar cómo suena, no un requisito para enterarte: quedarse
    callado porque Groq esté caído sería peor que decirlo con la frase sosa.
    """

    def test_hay_frase_de_reserva(self):
        frase = avisos.frase_sosa(_crudo())
        self.assertIn("WhatsApp", frase)
        self.assertIn("Ana", frase)

    def test_sin_cuerpo_tambien_se_dice_algo(self):
        frase = avisos.frase_sosa(_crudo(cuerpo=""))
        self.assertTrue(frase.strip())


class Enunciar(IsolatedAsyncioTestCase):
    async def test_se_usa_lo_que_dice_el_modelo(self):
        with patch.object(
            avisos, "_pedir_al_modelo",
            AsyncMock(return_value="Ana dice que si puedes quedar mañana a las cinco"),
        ):
            frase = await avisos.enunciar("u", _crudo())
        self.assertEqual(
            frase, "Ana dice que si puedes quedar mañana a las cinco"
        )

    async def test_si_el_modelo_falla_se_cae_a_la_frase_sosa(self):
        with patch.object(
            avisos, "_pedir_al_modelo", AsyncMock(side_effect=RuntimeError("caído"))
        ):
            frase = await avisos.enunciar("u", _crudo())
        self.assertEqual(frase, avisos.frase_sosa(_crudo()))

    async def test_si_el_modelo_devuelve_vacio_tambien(self):
        with patch.object(
            avisos, "_pedir_al_modelo", AsyncMock(return_value="   ")
        ):
            frase = await avisos.enunciar("u", _crudo())
        self.assertEqual(frase, avisos.frase_sosa(_crudo()))

    async def test_una_parrafada_del_modelo_se_recorta(self):
        with patch.object(
            avisos, "_pedir_al_modelo", AsyncMock(return_value="palabra " * 200)
        ):
            frase = await avisos.enunciar("u", _crudo())
        self.assertLessEqual(len(frase), avisos.MAX_FRASE)


class Recibir(IsolatedAsyncioTestCase):
    """El camino entero: llega del nodo, se filtra, se dice."""

    def setUp(self):
        """La escritura del evento se dobla: sin esto, ejecutar la suite deja
        `aviso_dicho` de mentira en la base de datos de verdad. Pasó."""
        parche = patch.object(avisos.db, "log_event")
        self.log_event = parche.start()
        self.addCleanup(parche.stop)

    async def test_lo_silenciado_no_llega_a_decirse(self):
        with patch.object(avisos, "_reglas", return_value=[S.Regla(app="NVIDIA App")]), \
             patch.object(avisos, "enunciar", AsyncMock()) as hablar, \
             patch.object(avisos, "_contar_al_companion", AsyncMock()) as contar:
            dicho = await avisos.recibir("u", _crudo(app="NVIDIA App"))
        self.assertFalse(dicho)
        hablar.assert_not_awaited()
        contar.assert_not_awaited()

    async def test_lo_que_pasa_se_enuncia_y_se_cuenta(self):
        with patch.object(avisos, "_reglas", return_value=[]), \
             patch.object(avisos, "enunciar", AsyncMock(return_value="Ana dice...")), \
             patch.object(avisos, "_contar_al_companion", AsyncMock()) as contar:
            dicho = await avisos.recibir("u", _crudo())
        self.assertTrue(dicho)
        contar.assert_awaited_once()
        self.assertEqual(contar.await_args[0][1], "Ana dice...")

    async def test_un_aviso_sin_contenido_se_descarta_sin_molestar(self):
        with patch.object(avisos, "_reglas", return_value=[]), \
             patch.object(avisos, "_contar_al_companion", AsyncMock()) as contar:
            dicho = await avisos.recibir("u", {"app": "", "titulo": "", "cuerpo": ""})
        self.assertFalse(dicho)
        contar.assert_not_awaited()


class Callar(IsolatedAsyncioTestCase):
    """«Esto no me lo digas más»: Vibi elige el alcance y lo dice."""

    async def test_se_guarda_la_regla_y_se_explica(self):
        with patch.object(avisos.db, "add_mute_rule",
                          return_value={"id": "r1", "app": "Discord", "patron": ""}):
            respuesta = await avisos.callar("u", app="Discord", patron="")
        self.assertEqual(respuesta["dicho"], "No vuelvo a decirte nada de Discord.")
        self.assertEqual(respuesta["regla"]["app"], "Discord")

    async def test_una_regla_vacia_no_calla_nada_y_lo_dice(self):
        with patch.object(avisos.db, "add_mute_rule", return_value=None):
            respuesta = await avisos.callar("u", app="", patron="")
        self.assertIsNone(respuesta["regla"])
        self.assertIn("no he callado nada", respuesta["dicho"].lower())

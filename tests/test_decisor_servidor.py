"""El modelo de decisión del lado del servidor.

Sin red. Lo que se prueba es la disciplina —cuándo se pregunta, cuándo se
acepta la respuesta y qué pasa cuando no la hay—, no si Jev acierta.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import decisor  # noqa: E402
from app.config import settings  # noqa: E402

OPCIONES = {"discord-1": "Discord", "discord-2": "Discord PTB"}


class RespuestaFalsa:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    def raise_for_status(self):
        return None

    def json(self):
        return self._cuerpo


def contestando(respuestas):
    return RespuestaFalsa({"answers": respuestas})


def eligiendo(opcion, confianza):
    return contestando({"cual": {"choice": opcion, "confidence": confianza}})


class ConKey(IsolatedAsyncioTestCase):
    def setUp(self):
        anterior = settings.opper_api_key
        settings.opper_api_key = "op-de-mentira"
        self.addCleanup(setattr, settings, "opper_api_key", anterior)

    def fingiendo(self, *args, **kwargs):
        return patch.object(
            decisor, "cliente", return_value=AsyncMock(post=AsyncMock(*args, **kwargs))
        )


class Disponibilidad(IsolatedAsyncioTestCase):
    def test_sin_key_no_hay_decisor(self):
        anterior = settings.opper_api_key
        settings.opper_api_key = ""
        self.addCleanup(setattr, settings, "opper_api_key", anterior)

        self.assertFalse(decisor.disponible())

    async def test_sin_key_ni_se_llama(self):
        anterior = settings.opper_api_key
        settings.opper_api_key = ""
        self.addCleanup(setattr, settings, "opper_api_key", anterior)

        with patch.object(decisor, "cliente") as cliente:
            self.assertIsNone(await decisor.desempatar("x", "¿?", OPCIONES))

        cliente.assert_not_called()


class Desempate(ConKey):
    async def test_devuelve_la_eleccion_cuando_va_seguro(self):
        with self.fingiendo(return_value=eligiendo("discord-2", 0.93)):
            elegida = await decisor.desempatar("estado", "¿cuál?", OPCIONES)

        self.assertEqual(elegida, "discord-2")

    async def test_por_debajo_del_umbral_no_elige(self):
        """Nunca dice «no lo sé»: la confianza es el único freno."""
        with self.fingiendo(return_value=eligiendo("discord-1", 0.62)):
            self.assertIsNone(await decisor.desempatar("estado", "¿?", OPCIONES))

    async def test_una_opcion_inventada_no_vale(self):
        with self.fingiendo(return_value=eligiendo("nunca-existio", 1.0)):
            self.assertIsNone(await decisor.desempatar("estado", "¿?", OPCIONES))

    async def test_un_fallo_de_red_deja_todo_como_estaba(self):
        with self.fingiendo(side_effect=httpx.ConnectError("sin red")):
            self.assertIsNone(await decisor.desempatar("estado", "¿?", OPCIONES))

    async def test_con_una_sola_opcion_no_se_gasta_una_llamada(self):
        with patch.object(decisor, "cliente") as cliente:
            self.assertIsNone(await decisor.desempatar("x", "¿?", {"a": "A"}))

        cliente.assert_not_called()

    async def test_un_timeout_no_para_nada(self):
        """Esto se mete delante de caminos que ya funcionaban."""
        with self.fingiendo(side_effect=httpx.ReadTimeout("tarde")):
            self.assertIsNone(await decisor.desempatar("estado", "¿?", OPCIONES))


class Peticion(ConKey):
    async def cuerpo_enviado(self, estado):
        post = AsyncMock(return_value=eligiendo("discord-1", 0.95))
        with patch.object(decisor, "cliente", return_value=AsyncMock(post=post)):
            await decisor.desempatar(estado, "¿cuál abro?", OPCIONES)
        return post.call_args

    async def test_el_estado_de_texto_va_tal_cual(self):
        llamada = await self.cuerpo_enviado("el árbol")

        self.assertEqual(llamada.kwargs["json"]["state"], "el árbol")

    async def test_un_estado_con_datos_va_como_json(self):
        llamada = await self.cuerpo_enviado({"pidio": "abre discord"})

        self.assertEqual(
            json.loads(llamada.kwargs["json"]["state"]), {"pidio": "abre discord"}
        )

    async def test_las_opciones_van_donde_jev_las_espera(self):
        llamada = await self.cuerpo_enviado("x")
        pregunta = llamada.kwargs["json"]["questions"]["cual"]

        self.assertEqual(pregunta["type"], "choice")
        self.assertEqual(pregunta["criteria"], OPCIONES)

    async def test_la_key_viaja_en_la_cabecera(self):
        llamada = await self.cuerpo_enviado("x")

        self.assertEqual(
            llamada.kwargs["headers"]["Authorization"], "Bearer op-de-mentira"
        )


class VariasPreguntas(ConKey):
    """El estado se manda una vez: dos preguntas cuestan lo que una."""

    PREGUNTAS = {
        "ruta": decisor.eleccion("¿qué hago?", {"a": "una", "b": "otra"}),
        "ok": decisor.juicio("¿puede esperar?"),
    }

    async def test_las_dos_vuelven_de_una_sola_llamada(self):
        post = AsyncMock(
            return_value=contestando({
                "ruta": {"choice": "b", "confidence": 0.9},
                "ok": {"noul": 0.7},
            })
        )
        with patch.object(decisor, "cliente", return_value=AsyncMock(post=post)):
            respuesta = await decisor.preguntar("estado", self.PREGUNTAS)

        self.assertEqual(post.await_count, 1)
        self.assertEqual(respuesta.eleccion("ruta").opcion, "b")
        self.assertAlmostEqual(respuesta.juicio("ok").probabilidad, 0.7)

    async def test_si_falta_una_respuesta_no_vale_ninguna(self):
        """Media respuesta es peor que ninguna: se decidiría a medias."""
        with self.fingiendo(
            return_value=contestando({"ruta": {"choice": "a", "confidence": 0.9}})
        ):
            self.assertIsNone(await decisor.preguntar("estado", self.PREGUNTAS))


class Comprobar(ConKey):
    async def test_por_encima_del_medio_es_que_si(self):
        with self.fingiendo(return_value=contestando({"ok": {"noul": 0.8}})):
            self.assertIs(await decisor.comprobar("estado", "¿salió bien?"), True)

    async def test_por_debajo_es_que_no(self):
        with self.fingiendo(return_value=contestando({"ok": {"noul": 0.2}})):
            self.assertIs(await decisor.comprobar("estado", "¿salió bien?"), False)

    async def test_sin_red_no_dice_ni_si_ni_no(self):
        with self.fingiendo(side_effect=httpx.ConnectError("sin red")):
            self.assertIsNone(await decisor.comprobar("estado", "¿?"))

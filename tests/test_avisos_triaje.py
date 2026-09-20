"""El triaje: qué merece un turno de agy y qué basta con contarlo.

Deliberar cuesta un turno entero —segundos, y puede abrir aplicaciones por el
camino—. Preguntar esto cuesta medio segundo. Lo que se prueba aquí es que el
atajo solo se toma cuando está claro, y que **el aviso llega siempre**, se
tome o no: descartar no es una de las salidas.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import avisos  # noqa: E402
from app import decisor as decisor_servidor  # noqa: E402

USUARIO = {"id": "u-1", "email": "quien@sea"}
COLA = [{"app": "WhatsApp", "titulo": "Ana", "cuerpo": "¿Quedamos mañana?"}]


def respondiendo(ruta, confianza, puede_esperar=None):
    respuestas = {
        "ruta": decisor_servidor.Eleccion(opcion=ruta, confianza=confianza)
    }
    if puede_esperar is not None:
        respuestas["puede_esperar"] = decisor_servidor.Juicio(
            probabilidad=puede_esperar
        )
    return decisor_servidor.Respuesta(respuestas=respuestas, ms=420)


class Ayudas:
    """Los parches comunes, como mixin y no como caso padre.

    Heredar de un caso vuelve a ejecutar sus pruebas dentro del hijo, y
    entonces la suite cuenta dos veces lo que solo se ha probado una.
    """

    def setUp(self):
        self.disponible = patch.object(
            avisos.decisor, "disponible", return_value=True
        )
        self.disponible.start()
        self.addCleanup(self.disponible.stop)

    def contestando(self, respuesta):
        return patch.object(
            avisos.decisor, "preguntar", AsyncMock(return_value=respuesta)
        )


class Triaje(Ayudas, IsolatedAsyncioTestCase):
    async def test_lo_que_no_pide_decision_se_cuenta_y_basta(self):
        with self.contestando(respondiendo("contar", 0.96)):
            self.assertEqual(await avisos._triar("u-1", COLA, ""), "contar")

    async def test_lo_que_pide_decision_se_delibera(self):
        with self.contestando(respondiendo("deliberar", 0.93)):
            self.assertEqual(await avisos._triar("u-1", COLA, ""), "deliberar")

    async def test_si_no_lo_tiene_claro_no_decide_nadie(self):
        """Por debajo del umbral se delibera, que es lo que se hacía antes."""
        with self.contestando(respondiendo("contar", 0.70)):
            self.assertIsNone(await avisos._triar("u-1", COLA, ""))

    async def test_el_umbral_va_por_encima_del_normal(self):
        """El fallo que se arriesga no se ve: el aviso llega igual, sin pensar."""
        self.assertGreater(avisos.UMBRAL_TRIAJE, 0.8)

    async def test_una_ruta_inventada_no_vale(self):
        with self.contestando(respondiendo("hacer_lo_que_sea", 0.99)):
            self.assertIsNone(await avisos._triar("u-1", COLA, ""))

    async def test_sin_decisor_ni_se_pregunta(self):
        with patch.object(avisos.decisor, "disponible", return_value=False):
            with patch.object(avisos.decisor, "preguntar", AsyncMock()) as preguntado:
                self.assertIsNone(await avisos._triar("u-1", COLA, ""))

        preguntado.assert_not_awaited()

    async def test_sin_red_se_delibera_como_siempre(self):
        with self.contestando(None):
            self.assertIsNone(await avisos._triar("u-1", COLA, ""))


class MientrasEspera(Ayudas, IsolatedAsyncioTestCase):
    """La pregunta de si esto puede esperar va en la misma petición."""

    async def test_solo_se_pregunta_cuando_hay_algo_que_esperar(self):
        preguntar = AsyncMock(return_value=respondiendo("contar", 0.95))
        with patch.object(avisos.decisor, "preguntar", preguntar):
            await avisos._triar("u-1", COLA, "")

        self.assertNotIn("puede_esperar", preguntar.await_args.args[1])

    async def test_con_una_vigilancia_viva_van_las_dos_preguntas_juntas(self):
        preguntar = AsyncMock(return_value=respondiendo("contar", 0.95, 0.3))
        with patch.object(avisos.decisor, "preguntar", preguntar):
            await avisos._triar("u-1", COLA, "que termine el build")

        self.assertEqual(preguntar.await_count, 1)
        self.assertIn("puede_esperar", preguntar.await_args.args[1])
        self.assertEqual(
            preguntar.await_args.args[0]["esta_esperando"], "que termine el build"
        )

    async def test_lo_que_puede_esperar_no_le_quita_el_turno_a_lo_que_espera(self):
        """Merecía deliberarse, pero aguanta: se cuenta y no se interrumpe."""
        with self.contestando(respondiendo("deliberar", 0.95, puede_esperar=0.9)):
            self.assertEqual(
                await avisos._triar("u-1", COLA, "que termine el build"), "contar"
            )

    async def test_lo_que_no_puede_esperar_se_delibera_igual(self):
        with self.contestando(respondiendo("deliberar", 0.95, puede_esperar=0.1)):
            self.assertEqual(
                await avisos._triar("u-1", COLA, "que termine el build"), "deliberar"
            )


class ElAvisoLlegaSiempre(IsolatedAsyncioTestCase):
    """La prueba que sostiene todo lo demás: nada se tira por el camino."""

    def test_descartar_no_es_una_de_las_salidas(self):
        """Que un modelo decida no contarte que Ana ha escrito es el fallo."""
        self.assertEqual(set(avisos.RUTAS), {"deliberar", "contar"})

    async def test_el_camino_barato_cuenta_todos_los_avisos(self):
        cola = [
            {"app": "WhatsApp", "titulo": "Ana", "cuerpo": "hola"},
            {"app": "Slack", "titulo": "Equipo", "cuerpo": "revisa esto"},
        ]
        contado = AsyncMock()
        with patch.object(avisos, "enunciar", AsyncMock(side_effect=["uno", "dos"])):
            with patch.object(avisos, "_contar_al_companion", contado):
                with patch.object(avisos.db, "log_event"):
                    await avisos._contar_sin_deliberar("u-1", cola)

        self.assertEqual(
            [llamada.args[1] for llamada in contado.await_args_list], ["uno", "dos"]
        )


class DentroDeLaDeliberacion(IsolatedAsyncioTestCase):
    """Que el triaje esté enchufado donde dice estarlo."""

    def setUp(self):
        avisos._pendientes.pop("u-1", None)
        self.addCleanup(avisos._pendientes.pop, "u-1", None)
        for nombre, valor in (
            ("get_user_by_id", USUARIO),
            ("list_notification_permissions", []),
            ("log_event", None),
        ):
            parche = patch.object(avisos.db, nombre, return_value=valor)
            parche.start()
            self.addCleanup(parche.stop)

    async def ejecutar(self, ruta, responder):
        avisos._pendientes["u-1"] = list(COLA)
        with patch.object(avisos, "_triar", AsyncMock(return_value=ruta)):
            with patch.object(
                avisos, "_contar_sin_deliberar", AsyncMock()
            ) as barato:
                with patch.dict(sys.modules, {"app.vigilancias": _vigilancias()}):
                    with patch(
                        "app.executors.chat.respond",
                        AsyncMock(return_value=responder),
                    ) as turno:
                        with patch.object(avisos.events, "avisos_deliberados", AsyncMock()):
                            await avisos._deliberar("u-1")
        return barato, turno

    async def test_contar_se_ahorra_el_turno_entero(self):
        barato, turno = await self.ejecutar("contar", None)

        barato.assert_awaited_once()
        turno.assert_not_awaited()

    async def test_deliberar_gasta_el_turno_como_siempre(self):
        barato, turno = await self.ejecutar(
            "deliberar", SimpleNamespace(response="ya lo miro")
        )

        barato.assert_not_awaited()
        turno.assert_awaited_once()

    async def test_sin_veredicto_se_delibera(self):
        """`None` significa «decide tú», y aquí decidir es hacer lo de antes."""
        barato, turno = await self.ejecutar(
            None, SimpleNamespace(response="ya lo miro")
        )

        barato.assert_not_awaited()
        turno.assert_awaited_once()


def _vigilancias():
    return SimpleNamespace(vivas=lambda _user_id: [])

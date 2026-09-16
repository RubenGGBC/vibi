"""Del aviso que manda el nodo a la frase que Vibi dice en voz alta."""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import avisos, presencia  # noqa: E402
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
    """El camino entero: llega del nodo, se filtra, y queda para deliberar."""

    def setUp(self):
        """La escritura del evento se dobla: sin esto, ejecutar la suite deja
        `aviso_dicho` de mentira en la base de datos de verdad. Pasó."""
        parche = patch.object(avisos.db, "log_event")
        self.log_event = parche.start()
        self.addCleanup(parche.stop)
        avisos._pendientes.pop("u", None)
        self.addCleanup(avisos._pendientes.pop, "u", None)

    async def test_lo_silenciado_no_llega_a_decirse(self):
        with patch.object(avisos, "_reglas", return_value=[S.Regla(app="NVIDIA App")]), \
             patch.object(avisos, "enunciar", AsyncMock()) as hablar, \
             patch.object(avisos, "_contar_al_companion", AsyncMock()) as contar:
            dicho = await avisos.recibir("u", _crudo(app="NVIDIA App"))
        self.assertFalse(dicho)
        hablar.assert_not_awaited()
        contar.assert_not_awaited()

    async def test_lo_que_pasa_espera_a_que_agy_delibere(self):
        """Ya no se locuta al llegar: se guarda para dárselo a agy con el turno
        libre. Hablar aquí es justo lo que le quitaría el turno al usuario."""
        with patch.object(avisos, "_reglas", return_value=[]), \
             patch.object(avisos, "enunciar", AsyncMock()) as hablar, \
             patch.object(avisos, "_contar_al_companion", AsyncMock()) as contar:
            dicho = await avisos.recibir("u", _crudo())
        self.assertFalse(dicho)
        hablar.assert_not_awaited()
        contar.assert_not_awaited()
        self.assertEqual(avisos.pendientes("u"), 1)

    async def test_lo_silenciado_ni_llega_a_la_cola(self):
        """El filtro va antes que agy para que un turno suyo, que cuesta
        segundos, no se gaste en una promoción de NVIDIA."""
        with patch.object(avisos, "_reglas", return_value=[S.Regla(app="NVIDIA App")]):
            await avisos.recibir("u", _crudo(app="NVIDIA App"))
        self.assertEqual(avisos.pendientes("u"), 0)

    async def test_un_aviso_sin_contenido_se_descarta_sin_molestar(self):
        with patch.object(avisos, "_reglas", return_value=[]), \
             patch.object(avisos, "_contar_al_companion", AsyncMock()) as contar:
            dicho = await avisos.recibir("u", {"app": "", "titulo": "", "cuerpo": ""})
        self.assertFalse(dicho)
        contar.assert_not_awaited()
        self.assertEqual(avisos.pendientes("u"), 0)

    async def test_la_cola_no_crece_sin_fin(self):
        with patch.object(avisos, "_reglas", return_value=[]):
            for i in range(avisos.MAX_PENDIENTES + 5):
                await avisos.recibir("u", _crudo(titulo=f"aviso {i}"))
        self.assertEqual(avisos.pendientes("u"), avisos.MAX_PENDIENTES)
        # Lo que se tira es lo más viejo, no lo que acaba de llegar.
        self.assertEqual(
            avisos._pendientes["u"][-1]["titulo"],
            f"aviso {avisos.MAX_PENDIENTES + 4}",
        )


class Deliberar(IsolatedAsyncioTestCase):
    """Lo acumulado se le da a agy en un turno, y si no puede, se cuenta soso."""

    def setUp(self):
        parche = patch.object(avisos.db, "log_event")
        self.log_event = parche.start()
        self.addCleanup(parche.stop)
        avisos._pendientes.pop("u", None)
        avisos._preguntas.pop("u", None)
        self.addCleanup(avisos._pendientes.pop, "u", None)
        self.addCleanup(avisos._preguntas.pop, "u", None)

    def _colar(self, cuantos=1):
        for i in range(cuantos):
            avisos.encolar("u", avisos.sanear(_crudo(titulo=f"Ana {i}")))

    @staticmethod
    def _turno(respuesta="Ana pregunta si quedáis mañana."):
        """Un `chat.respond` doblado que devuelve lo que devuelve el de verdad."""
        return AsyncMock(return_value=SimpleNamespace(response=respuesta))

    async def test_todo_lo_acumulado_va_en_un_solo_turno(self):
        """Tres notificaciones no son tres turnos de agy: cada uno cuesta
        segundos y puede abrir aplicaciones."""
        self._colar(3)
        responder = self._turno()
        with patch.object(avisos.db, "get_user_by_id", return_value={"id": "u"}), \
             patch.object(avisos.db, "list_notification_permissions", return_value=[]), \
             patch("app.executors.chat.respond", responder), \
             patch.object(avisos.events, "avisos_deliberados", AsyncMock()):
            await avisos._deliberar("u")
        responder.assert_awaited_once()
        prompt = responder.await_args[0][1]
        self.assertIn("Ana 0", prompt)
        self.assertIn("Ana 2", prompt)
        self.assertEqual(avisos.pendientes("u"), 0)

    async def test_los_permisos_ya_dados_van_en_el_encargo(self):
        """Para que no vuelva a preguntar lo que ya preguntó una vez."""
        self._colar()
        permisos = [
            {"app": "WhatsApp", "accion": "contestar que estoy ocupado",
             "permitido": True},
            {"app": "", "accion": "borrar archivos", "permitido": False},
        ]
        responder = self._turno()
        with patch.object(avisos.db, "get_user_by_id", return_value={"id": "u"}), \
             patch.object(avisos.db, "list_notification_permissions",
                          return_value=permisos), \
             patch("app.executors.chat.respond", responder), \
             patch.object(avisos.events, "avisos_deliberados", AsyncMock()):
            await avisos._deliberar("u")
        prompt = responder.await_args[0][1]
        self.assertIn("puedes en WhatsApp: contestar que estoy ocupado", prompt)
        self.assertIn("NO puedes: borrar archivos", prompt)

    async def test_el_globo_lleva_de_quien_era_y_que_dijo(self):
        """Sin esto el aviso del escritorio no dice nada: «Vibi ha mirado una
        notificación» obliga a abrir el chat para saber de qué iba."""
        avisos.encolar("u", avisos.sanear(_crudo(app="Discord")))
        avisado = AsyncMock()
        with patch.object(avisos.db, "get_user_by_id", return_value={"id": "u"}), \
             patch.object(avisos.db, "list_notification_permissions", return_value=[]), \
             patch("app.executors.chat.respond",
                   self._turno("Jam pregunta si puedes mirar el repo.")), \
             patch.object(avisos.events, "avisos_deliberados", avisado):
            await avisos._deliberar("u")
        _, kwargs = avisado.await_args
        self.assertEqual(kwargs["apps"], "Discord")
        self.assertEqual(kwargs["dicho"], "Jam pregunta si puedes mirar el repo.")
        self.assertEqual(kwargs["pregunta"], "")

    async def test_lo_que_agy_pregunta_sale_en_el_evento(self):
        """Es lo que enciende los botones de sí y no."""
        self._colar()

        async def turno(*_a, **_k):
            avisos.preguntar("u", "¿Contesto que estás ocupado?")
            return SimpleNamespace(response="¿Quieres que conteste por ti?")

        avisado = AsyncMock()
        with patch.object(avisos.db, "get_user_by_id", return_value={"id": "u"}), \
             patch.object(avisos.db, "list_notification_permissions", return_value=[]), \
             patch("app.executors.chat.respond", turno), \
             patch.object(avisos.events, "avisos_deliberados", avisado):
            await avisos._deliberar("u")
        self.assertEqual(
            avisado.await_args.kwargs["pregunta"], "¿Contesto que estás ocupado?"
        )
        # Y no se queda pegada para el turno siguiente.
        self.assertNotIn("u", avisos._preguntas)

    async def test_una_pregunta_de_un_turno_roto_no_se_arrastra(self):
        """Si el turno anterior murió con la pregunta puesta, encender los
        botones ahora sería pedir respuesta a algo que ya no existe."""
        avisos.preguntar("u", "pregunta vieja")
        self._colar()
        avisado = AsyncMock()
        with patch.object(avisos.db, "get_user_by_id", return_value={"id": "u"}), \
             patch.object(avisos.db, "list_notification_permissions", return_value=[]), \
             patch("app.executors.chat.respond", self._turno()), \
             patch.object(avisos.events, "avisos_deliberados", avisado):
            await avisos._deliberar("u")
        self.assertEqual(avisado.await_args.kwargs["pregunta"], "")

    async def test_una_vigilancia_viva_ya_no_desvia_el_aviso(self):
        """Antes, cualquier vigilancia viva mandaba el aviso a un juicio aparte
        y apagaba la deliberación entera sin dejar rastro. Ahora solo entra
        como contexto del encargo."""
        with patch.object(avisos, "_reglas", return_value=[]):
            await avisos.recibir("u", _crudo())
        self.assertEqual(avisos.pendientes("u"), 1)

        responder = self._turno()
        with patch.object(avisos.db, "get_user_by_id", return_value={"id": "u"}), \
             patch.object(avisos.db, "list_notification_permissions", return_value=[]), \
             patch("app.vigilancias.vivas",
                   return_value=[{"que_espero": "que termine el render"}]), \
             patch("app.executors.chat.respond", responder), \
             patch.object(avisos.events, "avisos_deliberados", AsyncMock()):
            await avisos._deliberar("u")
        responder.assert_awaited_once()
        prompt = responder.await_args[0][1]
        self.assertIn("que termine el render", prompt)
        self.assertIn("no le interrumpas", prompt)

    async def test_sin_vigilancia_no_se_habla_de_silencios(self):
        self._colar()
        responder = self._turno()
        with patch.object(avisos.db, "get_user_by_id", return_value={"id": "u"}), \
             patch.object(avisos.db, "list_notification_permissions", return_value=[]), \
             patch("app.vigilancias.vivas", return_value=[]), \
             patch("app.executors.chat.respond", responder), \
             patch.object(avisos.events, "avisos_deliberados", AsyncMock()):
            await avisos._deliberar("u")
        self.assertNotIn("no le interrumpas", responder.await_args[0][1])

    async def test_las_apps_no_se_repiten_en_el_titulo(self):
        avisos.encolar("u", avisos.sanear(_crudo(app="Discord", titulo="uno")))
        avisos.encolar("u", avisos.sanear(_crudo(app="Discord", titulo="dos")))
        avisos.encolar("u", avisos.sanear(_crudo(app="WhatsApp", titulo="tres")))
        self.assertEqual(avisos.apps_de(avisos._pendientes["u"]), "Discord, WhatsApp")

    async def test_si_agy_falla_el_aviso_llega_igual_por_lo_rapido(self):
        """Quedarse callado porque agy esté caído sería peor que sonar a
        máquina: lo que no se puede perder es que Ana ha escrito."""
        self._colar()
        with patch.object(avisos.db, "get_user_by_id", return_value={"id": "u"}), \
             patch.object(avisos.db, "list_notification_permissions", return_value=[]), \
             patch("app.executors.chat.respond",
                   AsyncMock(side_effect=RuntimeError("agy no está"))), \
             patch.object(avisos, "enunciar", AsyncMock(return_value="Ana dice...")), \
             patch.object(avisos, "_contar_al_companion", AsyncMock()) as contar:
            await avisos._deliberar("u")
        contar.assert_awaited_once()
        self.assertEqual(contar.await_args[0][1], "Ana dice...")

    async def test_si_agy_se_cuelga_no_deja_el_aviso_sin_contar(self):
        """El paso GENERIC cuelga turnos. Con tope, el aviso sale por lo soso;
        sin tope, se quedaría esperando para siempre."""
        self._colar()
        import asyncio

        async def nunca_vuelve(*_a, **_k):
            await asyncio.sleep(3600)

        with patch.object(avisos, "TIMEOUT_DELIBERACION", 0.01), \
             patch.object(avisos.db, "get_user_by_id", return_value={"id": "u"}), \
             patch.object(avisos.db, "list_notification_permissions", return_value=[]), \
             patch("app.executors.chat.respond", nunca_vuelve), \
             patch.object(avisos, "enunciar", AsyncMock(return_value="Ana dice...")), \
             patch.object(avisos, "_contar_al_companion", AsyncMock()) as contar:
            await avisos._deliberar("u")
        contar.assert_awaited_once()


class ColaYPresencia(IsolatedAsyncioTestCase):
    """El gate entero: mientras haya alguien delante, el aviso espera."""

    def setUp(self):
        parche = patch.object(avisos.db, "log_event")
        parche.start()
        self.addCleanup(parche.stop)
        avisos._pendientes.pop("u", None)
        avisos._deliberando.discard("u")
        presencia.olvidar("u")
        self.addCleanup(avisos._pendientes.pop, "u", None)
        self.addCleanup(presencia.olvidar, "u")
        self.addCleanup(avisos._deliberando.discard, "u")

    async def _dar_vueltas(self, deliberar):
        """Deja correr el worker lo justo para que reparta, y lo para."""
        import asyncio

        with patch.object(avisos, "_deliberar", deliberar):
            tarea = asyncio.create_task(avisos.deliberar_worker(0.01))
            await asyncio.sleep(0.08)
            tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarea

    async def test_con_la_cara_despierta_el_aviso_se_queda_en_cola(self):
        """Es la regla que pediste: mientras la cabecita esté ahí, no se toca
        el turno. Así no hay que decidir quién va primero."""
        avisos.encolar("u", avisos.sanear(_crudo()))
        presencia.cara("u", True)
        deliberar = AsyncMock()
        await self._dar_vueltas(deliberar)
        deliberar.assert_not_awaited()
        self.assertEqual(avisos.pendientes("u"), 1)

    async def test_con_el_hilo_recien_movido_tambien_espera(self):
        avisos.encolar("u", avisos.sanear(_crudo()))
        presencia.chat_se_movio("u")
        deliberar = AsyncMock()
        await self._dar_vueltas(deliberar)
        deliberar.assert_not_awaited()

    async def test_sin_nadie_delante_se_delibera(self):
        avisos.encolar("u", avisos.sanear(_crudo()))
        presencia.cara("u", False)
        deliberar = AsyncMock()
        await self._dar_vueltas(deliberar)
        deliberar.assert_awaited()

    async def test_no_se_delibera_dos_veces_a_la_vez(self):
        """El worker mira cada segundo y un turno de agy dura minutos: sin el
        cerrojo le daría el mismo aviso una y otra vez."""
        import asyncio

        avisos.encolar("u", avisos.sanear(_crudo()))
        presencia.cara("u", False)
        llamadas = []

        async def lento(user_id):
            llamadas.append(user_id)
            await asyncio.sleep(0.5)

        await self._dar_vueltas(lento)
        self.assertEqual(len(llamadas), 1)


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

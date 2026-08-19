"""El motor Antigravity: seguir el turno por el stream y caer a Claude si falla."""
import asyncio
import threading
import unittest
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from app.executors import agy_client, antigravity_chat, chat
from app.executors.agy_process import AgyUnavailable
from app.executors.chat_engine import ChatResult, ConversationChanged


class _ClienteFalso:
    """Un language server de mentira que entrega los trozos ya preparados.

    `eco_previo` imita lo que hace el de verdad: al abrir el stream vuelca el
    estado actual, que trae la respuesta del turno anterior ya terminada.
    """

    def __init__(self, trozos, done_al_final=True, eco_previo=None):
        self.trozos = trozos
        self.done_al_final = done_al_final
        self.eco_previo = eco_previo
        self.parado = []
        self.orden: list[str] = []
        self._conteos_usuario = iter((0, 1))

    def stream_updates(self, cascade_id, timeout=None, skip_text=""):
        # Se conecta al llamarlo, igual que el de verdad.
        self.orden.append("stream abierto")

        def producir():
            empezado = False
            if self.eco_previo is not None:
                if not (skip_text and self.eco_previo == skip_text):
                    empezado = True
                    yield agy_client.Update(text=self.eco_previo, done=True)
                    return
            for indice, texto in enumerate(self.trozos):
                ultimo = indice == len(self.trozos) - 1
                empezado = True
                if isinstance(texto, agy_client.Update):
                    yield texto
                else:
                    yield agy_client.Update(
                        text=texto, done=ultimo and self.done_al_final
                    )

        return producir()

    def conversations(self):
        return ["cascade-1"]

    def user_input_count(self, cascade_id):
        return next(self._conteos_usuario, 1)

    def stop(self, cascade_id):
        self.parado.append(cascade_id)


class _ClienteConHerramienta:
    """Un turno que se para a usar una herramienta por el medio.

    Reproduce lo que entrega el cliente de verdad en ese caso: el aviso previo
    llega con su paso ya cerrado —`done`— porque la frase está entera, pero el
    stream continúa, porque la herramienta aún no ha corrido. Solo el último
    `done`, el que cierra el iterador, acaba el turno.
    """

    def __init__(self):
        self.parado = []
        self.orden: list[str] = []

    def stream_updates(self, cascade_id, timeout=None, skip_text=""):
        self.orden.append("stream abierto")

        def producir():
            yield agy_client.Update(text="Ahora te lo", done=False)
            yield agy_client.Update(text="Ahora te lo busco.", done=True)
            yield agy_client.Update(text="Hacen veinticuatro", done=False)
            yield agy_client.Update(text="Hacen veinticuatro grados.", done=True)

        return producir()

    def conversations(self):
        return ["cascade-1"]

    def stop(self, cascade_id):
        self.parado.append(cascade_id)


class _ClienteConContadores:
    def __init__(self, conteos):
        self.conteos = list(conteos)

    def user_input_count(self, cascade_id):
        if len(self.conteos) > 1:
            return self.conteos.pop(0)
        return self.conteos[0]


class _ClienteQueSeTragaElTurnoEnOtra:
    """El turno entra, pero en la conversación equivocada.

    Es lo que pasa cuando el pseudoterminal escribe en la conversación ACTIVA
    del proceso y esa ya no es la que la sesión vigila: `/new` de otra sesión
    se la robó. `user_input_count` de la nuestra no sube nunca por mucho que se
    reteclee.
    """

    def __init__(self):
        self.otra = "cascade-ajena"
        self.entradas = {"cascade-1": 0, "cascade-ajena": 0}
        self.tecleos = 0

    def recibir_tecleo(self):
        self.tecleos += 1
        # Va a parar donde no la vigilamos.
        self.entradas[self.otra] += 1

    def conversations(self):
        return list(self.entradas)

    def user_input_count(self, cascade_id):
        return self.entradas.get(cascade_id, 0)


class _ClienteLentoConHerramienta:
    def __init__(self):
        self.parado = []

    def stream_updates(self, cascade_id, timeout=None, skip_text=""):
        def producir():
            yield agy_client.Update(activity=True, tools_running=True)
            time.sleep(0.03)
            yield agy_client.Update(text="Hecho.", done=True)

        return producir()

    def stop(self, cascade_id):
        self.parado.append(cascade_id)


class LocucionEnLaCara(unittest.IsolatedAsyncioTestCase):
    """La cara locuta según van llegando los trozos, no al final del turno."""

    def _sesion(self, cliente):
        return antigravity_chat._LiveSession(
            conversation_id="c", process=None, client=cliente, cascade_id="cascade-1"
        )

    async def test_solo_se_emite_el_texto_nuevo_de_cada_trozo(self):
        """El stream reenvía la respuesta entera; locutarla tal cual la repetiría."""
        cliente = _ClienteFalso(["Hace", "Hace sol", "Hace sol hoy."])

        with patch.object(
            antigravity_chat.events, "fragmento_chat", AsyncMock()
        ) as fragmento:
            respuesta = await antigravity_chat._consume_turn(
                self._sesion(cliente), {"id": "u"}, "c", turn_id="t"
            )

        self.assertEqual(respuesta, "Hace sol hoy.")
        emitidos = [call.args[3] for call in fragmento.await_args_list]
        self.assertEqual(emitidos, ["", "Hace", " sol", " hoy."])

    async def test_abre_el_turno_para_no_arrastrar_el_anterior(self):
        cliente = _ClienteFalso(["Hola"])

        with patch.object(
            antigravity_chat.events, "fragmento_chat", AsyncMock()
        ) as fragmento:
            await antigravity_chat._consume_turn(
                self._sesion(cliente), {"id": "u"}, "c", turn_id="t"
            )

        primera = fragmento.await_args_list[0]
        self.assertEqual(primera.args[3], "")
        self.assertTrue(primera.kwargs["reset"])

    async def test_cada_trozo_va_marcado_para_que_la_voz_no_espere(self):
        cliente = _ClienteFalso(["Hace sol.", "Hace sol. Y 24 grados."])

        with patch.object(
            antigravity_chat.events, "fragmento_chat", AsyncMock()
        ) as fragmento:
            await antigravity_chat._consume_turn(
                self._sesion(cliente), {"id": "u"}, "c", turn_id="t"
            )

        con_texto = [c for c in fragmento.await_args_list if c.args[3]]
        self.assertTrue(all(c.kwargs.get("boundary") for c in con_texto))

    async def test_no_da_por_bueno_el_eco_de_la_respuesta_anterior(self):
        """Al abrir el stream llega el turno anterior ya terminado.

        Sin descartarlo, el turno se cerraría al instante devolviendo lo que
        Vibi ya había dicho, y la cara lo locutaría otra vez.
        """
        cliente = _ClienteFalso(["Hace sol."], eco_previo="Preparada.")
        sesion = self._sesion(cliente)
        sesion.last_response = "Preparada."

        with patch.object(
            antigravity_chat.events, "fragmento_chat", AsyncMock()
        ) as fragmento:
            respuesta = await antigravity_chat._consume_turn(
                sesion, {"id": "u"}, "c", turn_id="t"
            )

        self.assertEqual(respuesta, "Hace sol.")
        emitidos = [call.args[3] for call in fragmento.await_args_list if call.args[3]]
        self.assertEqual(emitidos, ["Hace sol."])

    async def test_teclea_el_turno_despues_de_estar_escuchando(self):
        """Si se teclea antes de abrir el stream, se pierde la respuesta.

        Pasó de verdad contra el agy real: el turno entraba, el stream se
        abría tarde y solo llegaba el eco del turno anterior.
        """
        cliente = _ClienteFalso(["Hace sol."])
        sesion = self._sesion(cliente)

        async def enviar():
            cliente.orden.append("turno tecleado")

        with patch.object(antigravity_chat.events, "fragmento_chat", AsyncMock()):
            await antigravity_chat._consume_turn(
                sesion, {"id": "u"}, "c", turn_id="t", enviar=enviar
            )

        self.assertEqual(cliente.orden, ["stream abierto", "turno tecleado"])

    async def test_recuerda_la_respuesta_para_el_turno_siguiente(self):
        cliente = _ClienteFalso(["Hace sol."])
        sesion = self._sesion(cliente)

        with patch.object(antigravity_chat.events, "fragmento_chat", AsyncMock()):
            await antigravity_chat._consume_turn(sesion, {"id": "u"}, "c", "t")

        self.assertEqual(sesion.last_response, "Hace sol.")

    async def test_un_done_intermedio_no_da_el_turno_por_acabado(self):
        """El aviso previo a una herramienta cierra su paso, no el turno.

        El cliente ya lo sabe: cuando hay una herramienta a medias sigue
        entregando actualizaciones después de ese `done`. Pero aquí se cortaba
        igualmente en el primer `done` que llegara, así que el turno se quedaba
        en «Ahora te lo busco.» y lo que Vibi contestaba de verdad aparecía
        en el volcado del turno siguiente. Desde ahí la conversación entera va
        desfasada: cada pregunta recibe la respuesta de la anterior.
        """
        cliente = _ClienteConHerramienta()
        sesion = self._sesion(cliente)

        with patch.object(
            antigravity_chat.events, "fragmento_chat", AsyncMock()
        ) as fragmento:
            respuesta = await antigravity_chat._consume_turn(
                sesion, {"id": "u"}, "c", turn_id="t"
            )

        self.assertEqual(respuesta, "Hacen veinticuatro grados.")
        emitidos = [call.args[3] for call in fragmento.await_args_list if call.args[3]]
        self.assertEqual(
            emitidos,
            ["Ahora te lo", " busco.", "Hacen veinticuatro", " grados."],
        )

    async def test_un_latido_no_borra_ni_repite_la_respuesta(self):
        cliente = _ClienteFalso([
            agy_client.Update(text="Buscando", tools_running=True),
            agy_client.Update(activity=True, tools_running=True),
            agy_client.Update(text="Buscando resultado final", done=True),
        ])

        with patch.object(
            antigravity_chat.events, "fragmento_chat", AsyncMock()
        ) as fragmento:
            respuesta = await antigravity_chat._consume_turn(
                self._sesion(cliente), {"id": "u"}, "c", turn_id="t"
            )

        self.assertEqual(respuesta, "Buscando resultado final")
        emitidos = [call.args[3] for call in fragmento.await_args_list]
        self.assertEqual(emitidos, ["", "Buscando", " resultado final"])

    async def test_una_herramienta_activa_amplia_el_plazo_de_silencio(self):
        cliente = _ClienteLentoConHerramienta()

        with patch.object(antigravity_chat, "TURN_SILENCE_TIMEOUT", 0.01), \
                patch.object(antigravity_chat, "TOOL_SILENCE_TIMEOUT", 0.1):
            respuesta = await antigravity_chat._consume_turn(
                self._sesion(cliente), {"id": "u"}, "c", turn_id=None
            )

        self.assertEqual(respuesta, "Hecho.")

    async def test_sin_turno_no_emite_eventos_pero_devuelve_el_texto(self):
        """El precalentado usa esto: habla con agy sin enseñarlo en la cara."""
        cliente = _ClienteFalso(["Preparada."])

        with patch.object(
            antigravity_chat.events, "fragmento_chat", AsyncMock()
        ) as fragmento:
            respuesta = await antigravity_chat._consume_turn(
                self._sesion(cliente), {"id": "u"}, "c", turn_id=None
            )

        self.assertEqual(respuesta, "Preparada.")
        fragmento.assert_not_awaited()


class ConfirmarElTurnoTecleado(unittest.IsolatedAsyncioTestCase):
    def _sesion(self, cliente):
        return antigravity_chat._LiveSession(
            conversation_id="c", process=None, client=cliente,
            cascade_id="cascade-1"
        )

    async def test_reintenta_una_vez_si_el_primer_tecleo_no_se_registra(self):
        cliente = _ClienteConContadores([0, 0, 1])
        enviados = []

        async def enviar():
            enviados.append("turno")

        with patch.object(antigravity_chat, "INPUT_ACK_TIMEOUT", 0):
            await antigravity_chat._send_confirmed(
                self._sesion(cliente), enviar
            )

        self.assertEqual(enviados, ["turno", "turno"])

    async def test_no_teclea_en_una_conversacion_que_ya_no_es_la_activa(self):
        """El pseudoterminal escribe en la ACTIVA, no en la que vigilamos.

        Son 22 de las 47 caídas reales. Cuando otra sesión hace `/new`, la CLI
        cambia de conversación activa y la nuestra deja de recibir nada: el
        turno entra en la ajena, `user_input_count` de la nuestra no sube
        jamás, y el reteclado —pensado para cuando la CLI se come la entrada—
        solo consigue meterlo DOS veces donde no era.

        No hace falta preguntárselo a nadie: la activa es siempre la última que
        se abrió con `/new` en ese proceso, y eso lo sabemos al abrirla.
        """
        cliente = _ClienteQueSeTragaElTurnoEnOtra()
        sesion = self._sesion(cliente)
        sesion.process = _ProcesoFalso()
        sesion.process.conversacion_activa = "cascade-ajena"

        async def enviar():
            cliente.recibir_tecleo()

        with patch.object(antigravity_chat, "INPUT_ACK_TIMEOUT", 0):
            with self.assertRaises(AgyUnavailable) as caso:
                await antigravity_chat._send_confirmed(sesion, enviar)

        self.assertEqual(cliente.tecleos, 0, "no se escribe en la conversación ajena")
        self.assertIn("activa", str(caso.exception))

    async def test_con_la_conversacion_activa_teclea_con_normalidad(self):
        cliente = _ClienteConContadores([0, 1])
        sesion = self._sesion(cliente)
        sesion.process = _ProcesoFalso()
        sesion.process.conversacion_activa = "cascade-1"
        enviados = []

        async def enviar():
            enviados.append("turno")

        with patch.object(antigravity_chat, "INPUT_ACK_TIMEOUT", 0):
            await antigravity_chat._send_confirmed(sesion, enviar)

        self.assertEqual(enviados, ["turno"])

    async def test_si_de_verdad_se_perdio_si_reteclea(self):
        """El caso para el que se hizo el reintento sigue funcionando."""
        cliente = _ClienteConContadores([0, 0, 1])
        enviados = []

        async def enviar():
            enviados.append("turno")

        with patch.object(antigravity_chat, "INPUT_ACK_TIMEOUT", 0):
            await antigravity_chat._send_confirmed(self._sesion(cliente), enviar)

        self.assertEqual(enviados, ["turno", "turno"])

    async def test_dos_tecleos_sin_acuse_fallan(self):
        cliente = _ClienteConContadores([0, 0, 0])
        enviados = []

        async def enviar():
            enviados.append("turno")

        with patch.object(antigravity_chat, "INPUT_ACK_TIMEOUT", 0):
            with self.assertRaises(AgyUnavailable):
                await antigravity_chat._send_confirmed(
                    self._sesion(cliente), enviar
                )

        self.assertEqual(enviados, ["turno", "turno"])


class ElAcusePorTamano(unittest.TestCase):
    """Un tope fijo hacía que `agy` recibiera los turnos largos dos veces.

    La interfaz de la CLI digiere la entrada a ~8 ms por carácter, así que con
    tres segundos para todo, cualquier turno que pasara de unos 400 caracteres
    se daba por perdido y se volvía a teclear. Y no se había perdido: llegaba
    tarde, con lo que el mensaje entraba duplicado. Comprobado en uso real, con
    dos `HandleUserInput` idénticos.
    """

    def test_un_turno_corto_espera_poco(self):
        self.assertAlmostEqual(
            antigravity_chat.ack_timeout(100),
            antigravity_chat.INPUT_ACK_TIMEOUT + 1.2,
            places=3,
        )

    def test_un_turno_largo_espera_mas_en_vez_de_repetirse(self):
        """2.500 caracteres tardan 20,8 s medidos: hay que aguantarlos."""
        self.assertGreater(antigravity_chat.ack_timeout(2_500), 20.8)

    def test_sin_texto_se_queda_en_el_minimo(self):
        self.assertEqual(
            antigravity_chat.ack_timeout(0), antigravity_chat.INPUT_ACK_TIMEOUT
        )
        self.assertEqual(
            antigravity_chat.ack_timeout(-5), antigravity_chat.INPUT_ACK_TIMEOUT
        )


class _ClienteSinConversacion:
    """Imita a `agy` cuando se ha comido el primer turno tecleado."""

    def __init__(self, aparece_tras: int):
        self.consultas = 0
        self.aparece_tras = aparece_tras

    def conversations(self):
        self.consultas += 1
        return ["cascade-1"] if self.consultas > self.aparece_tras else []


class AbrirLaConversacion(unittest.IsolatedAsyncioTestCase):
    """Primero existir, después escribir.

    La CLI se come lo que se teclea mientras cambia de conversación, y pasa de
    forma intermitente. Por eso se pide la conversación, se espera a que
    aparezca, y solo entonces se le escribe dentro.
    """

    def _proceso(self, cliente):
        proceso = _ProcesoFalso()
        proceso.port = 1234
        self._cliente = cliente
        return proceso

    async def _abrir(self, cliente):
        proceso = self._proceso(cliente)
        with patch.object(antigravity_chat.agy_client, "AgyClient", return_value=cliente):
            cascade_id = await antigravity_chat._abrir_conversacion(proceso)
        return cascade_id, proceso

    async def test_devuelve_la_conversacion_en_cuanto_aparece(self):
        cliente = _ClienteSinConversacion(aparece_tras=1)

        cascade_id, proceso = await self._abrir(cliente)

        self.assertEqual(cascade_id, "cascade-1")
        self.assertEqual(proceso.tecleado, [antigravity_chat.COMANDO_CONVERSACION_NUEVA])

    async def test_si_se_pierde_la_peticion_se_repite_pronto(self):
        """Repetir abre una conversación de más; esperar deja el canal mudo."""
        cliente = _ClienteSinConversacion(aparece_tras=200)

        with patch.object(antigravity_chat, "REINTENTO_CONVERSACION", 0.05), \
                patch.object(antigravity_chat, "CONVERSATION_TIMEOUT", 1.0):
            proceso = self._proceso(cliente)
            with patch.object(
                antigravity_chat.agy_client, "AgyClient", return_value=cliente
            ), self.assertRaises(AgyUnavailable):
                await antigravity_chat._abrir_conversacion(proceso)

        # Varias peticiones en un segundo, no una sola a media espera.
        self.assertGreater(len(proceso.tecleado), 2)
        self.assertTrue(proceso.muerto)


class _ProcesoFalso:
    def __init__(self, colgado=False):
        self.tecleado: list[str] = []
        self.muerto = False
        # Con el pseudoterminal abierto pero la CLI sin aceptar entrada: es
        # como se cuelga `agy` de verdad, y por eso `alive()` no lo detecta.
        self.colgado = colgado
        self.port = 1234
        self.log_conservado = False

    def type(self, texto):
        self.tecleado.append(texto)

    def alive(self):
        return not self.muerto

    def healthy(self):
        return not self.muerto and not self.colgado

    def kill(self, conservar_log=False):
        self.muerto = True
        self.log_conservado = conservar_log


class ReutilizarElProceso(unittest.IsolatedAsyncioTestCase):
    """Cerrar una conversación no puede matar a `agy`.

    El canal de voz reinicia la conversación cada vez que invocas a Vibi, y
    eso llamaba a `close_session`. Como el proceso moría, el turno siguiente
    tenía que arrancarlo entero: 13-42 s de espera medidos en uso real. La CLI
    sabe empezar conversación nueva sola con `/new`, en 1 s.
    """

    def setUp(self):
        antigravity_chat._sessions.clear()
        antigravity_chat._processes.clear()
        self.addCleanup(antigravity_chat._sessions.clear)
        self.addCleanup(antigravity_chat._processes.clear)

    async def test_cerrar_la_conversacion_deja_agy_en_pie(self):
        proceso = _ProcesoFalso()
        antigravity_chat._processes["u"] = proceso
        antigravity_chat._sessions["c1"] = antigravity_chat._LiveSession(
            conversation_id="c1", process=proceso, client=None,
            cascade_id="casc-1", user_id="u",
        )

        await antigravity_chat.close_session("c1")

        self.assertFalse(proceso.muerto)
        self.assertNotIn("c1", antigravity_chat._sessions)

    async def test_apagar_el_servidor_si_mata_los_procesos(self):
        proceso = _ProcesoFalso()
        antigravity_chat._processes["u"] = proceso

        await antigravity_chat.close_all_sessions()

        self.assertTrue(proceso.muerto)

    async def test_la_conversacion_siguiente_reaprovecha_el_proceso(self):
        """Levantar la CLI cuesta una decena de segundos; reusarla, décimas."""
        proceso = _ProcesoFalso()
        antigravity_chat._processes["u"] = proceso

        reutilizado = await antigravity_chat._process_for(
            {"id": "u", "nombre": "R"}, workspace="/tmp"
        )

        self.assertIs(reutilizado, proceso)
        # Pedir la conversación ya no es cosa suya: eso lo hace quien va a
        # escribir en ella, que es el único que puede esperar a que exista.
        self.assertEqual(proceso.tecleado, [])


class DescartarElProcesoEnfermo(unittest.IsolatedAsyncioTestCase):
    """Un `agy` colgado tiene que morir, no reciclarse.

    Este era el fallo que dejaba a Vibi contestando por Claude para
    siempre: el turno fallaba, `close_session` olvidaba la conversación pero
    dejaba el proceso en pie a propósito, y el turno siguiente lo reutilizaba
    porque `alive()` solo mira si el pseudoterminal respira. La CLI atascada
    pasaba el examen una y otra vez.
    """

    def setUp(self):
        antigravity_chat._sessions.clear()
        antigravity_chat._processes.clear()
        antigravity_chat._process_touch.clear()
        self.addCleanup(antigravity_chat._sessions.clear)
        self.addCleanup(antigravity_chat._processes.clear)
        self.addCleanup(antigravity_chat._process_touch.clear)

    def _sesion(self, proceso):
        return antigravity_chat._LiveSession(
            conversation_id="c1", process=proceso, client=None,
            cascade_id="casc-1", user_id="u",
        )

    async def test_un_proceso_colgado_no_se_reutiliza(self):
        colgado = _ProcesoFalso(colgado=True)
        antigravity_chat._processes["u"] = colgado
        nuevo = _ProcesoFalso()

        with patch.object(
            antigravity_chat, "asegurar_playwright", AsyncMock(return_value="")
        ), patch.object(
            antigravity_chat.system_link, "asegurar_sistema", AsyncMock(return_value="")
        ), patch.object(
            antigravity_chat, "escribir_configuracion_mcp"
        ), patch.object(
            antigravity_chat.agy_process.AgyProcess, "start", return_value=nuevo
        ):
            devuelto = await antigravity_chat._process_for(
                {"id": "u", "nombre": "R"}, workspace="/tmp"
            )

        self.assertIs(devuelto, nuevo)
        self.assertTrue(colgado.muerto, "el colgado se queda comiendo memoria y cuota")

    async def test_abandonar_mata_el_proceso_enfermo_y_olvida_sus_sesiones(self):
        proceso = _ProcesoFalso(colgado=True)
        antigravity_chat._processes["u"] = proceso
        antigravity_chat._process_touch["u"] = 0.0
        antigravity_chat._sessions["c1"] = self._sesion(proceso)

        await antigravity_chat.abandonar("u", "agy no registró el turno tecleado")

        self.assertTrue(proceso.muerto)
        self.assertNotIn("u", antigravity_chat._processes)
        self.assertNotIn("c1", antigravity_chat._sessions)
        # Su log es la única prueba de si el turno llegó a entrar en la CLI.
        self.assertTrue(proceso.log_conservado)

    async def test_un_turno_atascado_no_se_lleva_por_delante_un_agy_sano(self):
        """Matarlo era la reacción a cualquier fallo, y casi nunca tocaba.

        En las veinte caídas por «dejó de dar señales durante 60 s» el proceso
        estaba perfectamente: su propio log dice `executor is not currently
        running` cuando se le corta. Lo que se había atascado era una petición
        a Google, no la CLI. Matarlo tiraba la conversación y el contexto, y
        cobraba los diez segundos de arranque en el turno siguiente — que es
        justo lo que se vive como «solo aguanta un turno».

        La sesión sí se suelta: la conversación puede haber quedado con el
        ejecutor ocupado, y `_get_session` abrirá otra limpia sobre el mismo
        proceso, que cuesta décimas.
        """
        proceso = _ProcesoFalso()
        antigravity_chat._processes["u"] = proceso
        antigravity_chat._process_touch["u"] = 0.0
        antigravity_chat._sessions["c1"] = self._sesion(proceso)

        await antigravity_chat.abandonar("u", "agy dejó de dar señales durante 60 s")

        self.assertFalse(proceso.muerto, "un turno lento no es un proceso roto")
        self.assertIn("u", antigravity_chat._processes)
        self.assertNotIn("c1", antigravity_chat._sessions)

    async def test_abandonar_no_toca_las_sesiones_de_otro_usuario(self):
        mio, ajeno = _ProcesoFalso(), _ProcesoFalso()
        antigravity_chat._processes["u"] = mio
        antigravity_chat._processes["otro"] = ajeno
        sesion_ajena = antigravity_chat._LiveSession(
            conversation_id="c2", process=ajeno, client=None,
            cascade_id="casc-2", user_id="otro",
        )
        antigravity_chat._sessions["c2"] = sesion_ajena

        await antigravity_chat.abandonar("u", "fallo")

        self.assertFalse(ajeno.muerto)
        self.assertIn("c2", antigravity_chat._sessions)


class ApuntarLoQueTardaElTurno(unittest.TestCase):
    """Sin medir los tramos por separado no se sabe qué hay que arreglar."""

    def test_un_turno_normal_no_ensucia_la_actividad(self):
        with patch.object(antigravity_chat, "log") as registro:
            with patch("app.db.log_event") as evento:
                antigravity_chat._apuntar_tiempos(
                    "u", {"route": "agy", "total_ms": 1_600}
                )

        evento.assert_not_called()
        registro.info.assert_not_called()

    def test_un_turno_lento_queda_registrado_con_sus_tramos(self):
        etapas = {
            "route": "agy",
            "route_decision_ms": 1,
            "session_health_ms": 20_000,
            "stream_open_ms": 20,
            "input_ack_ms": 30,
            "time_to_first_text_ms": 500,
            "tool_running_ms": 250,
            "node_dispatch_ms": 0,
            "node_execution_ms": 0,
            "post_tool_ms": 40,
            "total_ms": 22_000,
        }
        with patch("app.db.log_event") as evento:
            antigravity_chat._apuntar_tiempos("u", etapas)

        evento.assert_called_once_with("turno_lento", "u", **etapas)


class ReinyectarElHistorial(unittest.TestCase):
    """Una sesión apuntada en la tabla no significa que su proceso siga vivo."""

    def setUp(self):
        antigravity_chat._sessions.clear()
        self.addCleanup(antigravity_chat._sessions.clear)

    def _sesion(self, proceso):
        return antigravity_chat._LiveSession(
            conversation_id="c1", process=proceso, client=None,
            cascade_id="casc-1", user_id="u",
        )

    def test_sin_sesion_hay_que_reconstruirlo(self):
        self.assertTrue(antigravity_chat.ENGINE.needs_history({"id": "c1"}))

    def test_con_el_proceso_vivo_y_la_sesion_estrenada_ya_esta_dentro(self):
        sesion = self._sesion(_ProcesoFalso())
        sesion.virgen = False  # ya ha pasado por ella algún turno

        antigravity_chat._sessions["c1"] = sesion

        self.assertFalse(antigravity_chat.ENGINE.needs_history({"id": "c1"}))

    def test_si_el_proceso_murio_hay_que_reconstruirlo(self):
        """Este era el agujero: la entrada sobrevivía a su propio proceso.

        `_get_session` detectaba el cadáver y reabría, pero para entonces
        `chat.py` ya había decidido no cargar el historial, así que Vibi
        empezaba de cero sin avisar a nadie.
        """
        proceso = _ProcesoFalso()
        proceso.kill()
        antigravity_chat._sessions["c1"] = self._sesion(proceso)

        self.assertTrue(antigravity_chat.ENGINE.needs_history({"id": "c1"}))


class ElHistorialTieneQueCaberPorElPseudoterminal(unittest.TestCase):
    """El bloque de historial se teclea, y el pseudoterminal tiene un techo.

    Medido contra la CLI de verdad: hasta 3.000 caracteres llegan intactos
    siempre (4 de 4), en 4.000 se pierde uno de cada dos, y con 12.000 —que era
    justo el tope con el que se pedía el historial— o no llega nada o el
    `write` se queda bloqueado más de dos minutos porque la interfaz consume a
    80 caracteres por segundo. Un turno así se perdía o agotaba su tiempo.
    """

    def test_un_historial_corto_va_entero(self):
        bloque = antigravity_chat._bloque_historial(
            ({"role": "user", "content": "hola"},
             {"role": "assistant", "content": "dime"})
        )

        self.assertIn("hola", bloque)
        self.assertIn("dime", bloque)

    def test_sin_mensajes_no_hay_bloque(self):
        self.assertEqual(antigravity_chat._bloque_historial(()), "")

    def test_uno_largo_se_recorta_en_vez_de_perder_el_turno(self):
        mensajes = ({"role": "user", "content": "x" * 40_000},)

        bloque = antigravity_chat._bloque_historial(mensajes)

        self.assertLessEqual(
            len(bloque),
            antigravity_chat.MAX_HISTORIAL_CHARS + 400,  # el envoltorio aparte
        )

    def test_cuando_no_cabe_todo_se_queda_lo_mas_reciente(self):
        """Lo viejo es lo prescindible: la conversación va hacia delante."""
        mensajes = tuple(
            {"role": "user", "content": f"mensaje-{numero:03d} " + "y" * 200}
            for numero in range(60)
        )

        bloque = antigravity_chat._bloque_historial(mensajes)

        self.assertIn("mensaje-059", bloque)
        self.assertNotIn("mensaje-000", bloque)

    def test_el_tope_cabe_en_una_espera_defendible(self):
        """A 8 ms por carácter, el tope es latencia antes de pensar nada."""
        espera = antigravity_chat.MAX_HISTORIAL_CHARS * 0.008

        self.assertLess(espera, 6.0, "el historial haría esperar demasiado")

    def test_avisa_de_que_va_recortado(self):
        """Si no, el modelo cree que eso es la conversación entera."""
        mensajes = tuple(
            {"role": "user", "content": f"m{numero} " + "z" * 300}
            for numero in range(40)
        )

        bloque = antigravity_chat._bloque_historial(mensajes)

        self.assertIn("recorta", bloque.lower())


class LaSesionDelPrecalentadoNoNaceAmnesica(unittest.IsolatedAsyncioTestCase):
    """El precalentado monta la sesión cuando todavía no hay nada que contarle.

    Es la sesión que queda tras una caída a Claude y tras arrancar el servidor,
    y se monta sin historial porque quien la pide no lo tiene. Nadie volvía a
    ofrecérselo: en cuanto la sesión figuraba montada y su proceso vivo,
    `needs_history` decía que no hacía falta y `_get_session` tiraba el que le
    llegara. Así que esa conversación de `agy` empezaba de cero y se quedaba
    así.

    Es lo que se vio en uso real: el turno se fue a Claude, el motor se relanzó
    solo, y a la pregunta siguiente Vibi contestó que la primera cosa que le
    habían dicho era la penúltima frase. Sin un solo error por medio.
    """

    def setUp(self):
        antigravity_chat._sessions.clear()
        antigravity_chat._process_touch.clear()
        self.addCleanup(antigravity_chat._sessions.clear)
        self.addCleanup(antigravity_chat._process_touch.clear)
        self.historial = (
            {"role": "user", "content": "¿me lees la arquitectura?"},
            {"role": "assistant", "content": "No he encontrado el archivo."},
        )

    def _montar_sesion_sin_estrenar(self):
        sesion = antigravity_chat._LiveSession(
            conversation_id="c1", process=_ProcesoFalso(), client=None,
            cascade_id="casc-1", user_id="u",
        )
        antigravity_chat._sessions["c1"] = sesion
        return sesion

    def test_una_sesion_sin_estrenar_pide_el_historial(self):
        self._montar_sesion_sin_estrenar()

        self.assertTrue(antigravity_chat.ENGINE.needs_history({"id": "c1"}))

    async def test_el_historial_entra_en_la_sesion_que_dejo_el_precalentado(self):
        """Llegaba hasta aquí y se descartaba por estar la sesión montada."""
        sesion = self._montar_sesion_sin_estrenar()

        devuelta = await antigravity_chat._get_session(
            {"id": "u", "nombre": "R"}, "c1", self.historial
        )

        self.assertIs(devuelta, sesion)
        self.assertIn("¿me lees la arquitectura?", sesion.historial_pendiente)
        self.assertIn("No he encontrado el archivo.", sesion.historial_pendiente)

    async def test_una_sesion_ya_estrenada_no_lo_vuelve_a_meter(self):
        """Repetirlo le contaría dos veces lo que ya tiene dentro."""
        sesion = self._montar_sesion_sin_estrenar()
        sesion.virgen = False

        await antigravity_chat._get_session(
            {"id": "u", "nombre": "R"}, "c1", self.historial
        )

        self.assertEqual(sesion.historial_pendiente, "")

    async def test_el_primer_turno_se_lleva_el_historial_por_delante(self):
        """De poco sirve guardarlo si no viaja pegado al turno que se teclea."""
        sesion = self._montar_sesion_sin_estrenar()

        with patch.object(
            antigravity_chat, "_consume_turn", AsyncMock(return_value="Ya la leo.")
        ) as consumir:
            await antigravity_chat.ENGINE.run_turn(
                {"id": "u", "nombre": "R"}, {"id": "c1"}, "está en mi ordenador",
                (), "t1", self.historial, voz=False,
            )
            await consumir.await_args.kwargs["enviar"]()

        tecleado = sesion.process.tecleado[0]
        self.assertIn("¿me lees la arquitectura?", tecleado)
        self.assertIn("está en mi ordenador", tecleado)
        # Y la sesión queda estrenada: no hay que volver a contárselo.
        self.assertFalse(sesion.virgen)
        self.assertEqual(sesion.historial_pendiente, "")


class QuedarseConLaConversacionNueva(unittest.IsolatedAsyncioTestCase):
    """Tras `/new` conviven varias conversaciones en el mismo proceso.

    Coger «la primera» devolvía la vieja, y Vibi habría seguido leyendo el
    hilo que el usuario acababa de cerrar.
    """

    async def test_ignora_las_que_ya_existian(self):
        class _Cliente:
            def __init__(self):
                self.veces = 0

            def conversations(self):
                self.veces += 1
                # La primera consulta es la foto de las que ya había.
                if self.veces < 2:
                    return ["vieja"]
                return ["vieja", "nueva"]

        proceso = _ProcesoFalso()
        cliente = _Cliente()

        with patch.object(
            antigravity_chat.agy_client, "AgyClient", return_value=cliente
        ):
            cascade_id = await antigravity_chat._abrir_conversacion(proceso)

        self.assertEqual(cascade_id, "nueva")


class CaidaAClaude(unittest.IsolatedAsyncioTestCase):
    """Si Antigravity falla, el usuario recibe respuesta igualmente."""

    def _engine(self, name: str, resultado=None, error=None):
        engine = AsyncMock()
        engine.name = name
        engine.display_name = name.capitalize()
        engine.run_turn = AsyncMock(return_value=resultado, side_effect=error)
        return engine

    async def test_el_fallo_del_motor_lo_contesta_claude(self):
        roto = self._engine("antigravity", error=RuntimeError("agy no responde"))
        claude = self._engine("anthropic", resultado=ChatResult(response="Hace sol."))

        with patch.object(
            chat, "_engines", return_value={"anthropic": claude, "antigravity": roto}
        ), patch.object(chat.db, "list_context_messages", return_value=[]), patch.object(
            chat, "precalentar_en_segundo_plano"
        ):
            result = await chat._run_with_fallback(
                roto, {"id": "u", "nombre": "R"}, {"id": "c"}, "hola", (), "t", (), False
            )

        self.assertIn("Hace sol.", result.response)
        self.assertIn("no estaba disponible", result.response)
        self.assertEqual(result.telemetry, {"route": "fallback"})

    async def test_el_motor_caido_se_abandona_no_solo_se_olvida(self):
        """Olvidar la conversación dejaba vivo el `agy` que acababa de fallar."""
        roto = self._engine("antigravity", error=RuntimeError("agy no responde"))
        claude = self._engine("anthropic", resultado=ChatResult(response="Hace sol."))

        with patch.object(
            chat, "_engines", return_value={"anthropic": claude, "antigravity": roto}
        ), patch.object(chat.db, "list_context_messages", return_value=[]), patch.object(
            chat, "precalentar_en_segundo_plano"
        ):
            await chat._run_with_fallback(
                roto, {"id": "u", "nombre": "R"}, {"id": "c"}, "hola", (), "t", (), False
            )

        roto.abandon_session.assert_awaited_once()
        usuario, conversation_id, motivo = roto.abandon_session.await_args.args
        self.assertEqual(usuario["id"], "u")
        self.assertEqual(conversation_id, "c")
        self.assertIn("agy no responde", motivo)
        roto.close_session.assert_not_awaited()

    async def test_tras_la_caida_el_motor_se_relanza_en_segundo_plano(self):
        """Que el turno siguiente lo encuentre sano en vez de roto otra vez.

        Es la mitad que faltaba: sin esto el usuario se quedaba en Claude
        hasta reiniciar el servidor, pagando además el timeout de `agy` en
        cada mensaje.
        """
        roto = self._engine("antigravity", error=RuntimeError("agy no responde"))
        claude = self._engine("anthropic", resultado=ChatResult(response="Hace sol."))
        conversation = {"id": "c"}

        with patch.object(
            chat, "_engines", return_value={"anthropic": claude, "antigravity": roto}
        ), patch.object(chat.db, "list_context_messages", return_value=[]), patch.object(
            chat, "precalentar_en_segundo_plano"
        ) as precalentar:
            await chat._run_with_fallback(
                roto, {"id": "u", "nombre": "R"}, conversation, "hola", (), "t", (), False
            )

        precalentar.assert_called_once()
        self.assertIs(precalentar.call_args.args[1], conversation)

    async def test_por_voz_el_aviso_no_se_locuta(self):
        """La cara dice la respuesta entera, corchetes y traza incluidos."""
        roto = self._engine("antigravity", error=RuntimeError("agy no responde"))
        claude = self._engine("anthropic", resultado=ChatResult(response="Hace sol."))

        with patch.object(
            chat, "_engines", return_value={"anthropic": claude, "antigravity": roto}
        ), patch.object(chat.db, "list_context_messages", return_value=[]), patch.object(
            chat, "precalentar_en_segundo_plano"
        ):
            result = await chat._run_with_fallback(
                roto, {"id": "u", "nombre": "R"}, {"id": "c"}, "hola", (), "t", (), True
            )

        self.assertEqual(result.response, "Hace sol.")
        self.assertEqual(result.telemetry, {"route": "fallback"})

    async def test_si_claude_tambien_falla_se_propaga(self):
        """Sin red de seguridad debajo, el error tiene que verse."""
        claude = self._engine("anthropic", error=RuntimeError("sin API key"))

        with patch.object(chat, "_engines", return_value={"anthropic": claude}):
            with self.assertRaises(RuntimeError):
                await chat._run_with_fallback(
                    claude, {"id": "u", "nombre": "R"}, {"id": "c"}, "hola", (), "t", (), False
                )

    async def test_el_cambio_de_conversacion_no_dispara_el_respaldo(self):
        """No es un fallo del motor: es que el usuario cambió de conversación."""
        roto = self._engine("antigravity", error=ConversationChanged())
        claude = self._engine("anthropic", resultado=ChatResult(response="no debería"))

        with patch.object(
            chat, "_engines", return_value={"anthropic": claude, "antigravity": roto}
        ):
            with self.assertRaises(ConversationChanged):
                await chat._run_with_fallback(
                    roto, {"id": "u", "nombre": "R"}, {"id": "c"}, "hola", (), "t", (), False
                )

        claude.run_turn.assert_not_awaited()


class LaPersonalidadVaEnElArchivoDeReglas(unittest.TestCase):
    """Teclear cuesta ~7 ms por carácter: la interfaz no traga más rápido.

    Presentarse costaba diez segundos por invocación y las instrucciones de
    locución otros catorce en cada turno hablado. `agy` lee solo los
    `GEMINI.md` de su directorio, así que ese texto puede estar puesto de
    antemano y el turno limitarse a lo que el usuario ha dicho de verdad.
    """

    def test_escribe_las_reglas_con_el_nombre_del_usuario(self):
        with TemporaryDirectory() as workspace:
            antigravity_chat.escribir_reglas(workspace, "Ruben")

            reglas = Path(workspace) / antigravity_chat.ARCHIVO_REGLAS
            self.assertTrue(reglas.is_file())
            contenido = reglas.read_text(encoding="utf-8")
            self.assertIn("Ruben", contenido)
            # Las reglas de voz viajan aquí, no pegadas a cada turno.
            self.assertIn(antigravity_chat.MARCA_VOZ, contenido)

    def test_le_dice_que_la_busqueda_web_la_pone_ella_misma(self):
        """Lo que `agy` sabe hacer solo, que lo haga solo.

        Antes había que elegir entre tres caminos para enterarse de algo:
        `exa_*`, el navegador y su propio `search_web`. Exa ya no se declara, y
        el navegador es para actuar dentro de una web, no para consultarla.
        """
        with TemporaryDirectory() as workspace:
            antigravity_chat.escribir_reglas(workspace, "Ruben", navegador=True)

            contenido = (
                Path(workspace) / antigravity_chat.ARCHIVO_REGLAS
            ).read_text(encoding="utf-8")

        self.assertIn("search_web", contenido)
        # Y sin ofrecerle el camino que ya no existe.
        self.assertNotIn("exa_", contenido)

    def test_con_el_disco_propio_le_habla_de_sus_herramientas(self):
        """Ya no vive en un contenedor: su terminal ES la del usuario.

        El bloque de `pc_*` existía para cruzar la frontera del contenedor.
        Corriendo en el ordenador, mantenerlo le ofrece un segundo camino para
        lo que ya sabe hacer y le hace leerse los esquemas antes de elegir.
        """
        with TemporaryDirectory() as workspace:
            antigravity_chat.escribir_reglas(
                workspace, "Ruben", disco_propio=True
            )

            contenido = (
                Path(workspace) / antigravity_chat.ARCHIVO_REGLAS
            ).read_text(encoding="utf-8")

        self.assertNotIn("pc_ejecutar", contenido)
        self.assertNotIn("contenedor", contenido)
        self.assertIn("run_command", contenido)

    def test_el_disco_de_otra_maquina_si_lleva_el_bloque_de_pc(self):
        """La malla no se toca: ahí `agy` no llega por su cuenta."""
        with TemporaryDirectory() as workspace:
            antigravity_chat.escribir_reglas(
                workspace, "Ruben", ordenador=True
            )

            contenido = (
                Path(workspace) / antigravity_chat.ARCHIVO_REGLAS
            ).read_text(encoding="utf-8")

        self.assertIn("pc_ejecutar", contenido)

    def test_con_navegador_le_prohibe_abrir_webs_por_la_terminal(self):
        """Corriendo en el ordenador tiene `run_command`, y con él abrir una web
        es un `Start-Process` trivial. Eso se lleva por delante el navegador de
        verdad: se abre el predeterminado del sistema, sin las sesiones del
        usuario y donde Vibi no ve nada. Pasó el 19/08/2026 pidiéndole Netflix
        en Opera GX.
        """
        with TemporaryDirectory() as workspace:
            antigravity_chat.escribir_reglas(
                workspace, "Ruben", navegador=True, disco_propio=True
            )
            contenido = (
                Path(workspace) / antigravity_chat.ARCHIVO_REGLAS
            ).read_text(encoding="utf-8")

        self.assertIn("browser_navigate", contenido)
        # Y lo dice donde se decide, no en una nota al pie.
        bloque = contenido[contenido.index("## El navegador"):]
        self.assertIn("terminal", bloque.lower())

    def test_sin_navegador_le_dice_que_lo_diga_en_vez_de_improvisar(self):
        """Sin navegador declarado, callarse es peor: abre el predeterminado con
        la terminal y le asegura al usuario que ha hecho lo que le pedía."""
        with TemporaryDirectory() as workspace:
            antigravity_chat.escribir_reglas(
                workspace, "Ruben", navegador=False, disco_propio=True
            )
            contenido = (
                Path(workspace) / antigravity_chat.ARCHIVO_REGLAS
            ).read_text(encoding="utf-8")

        self.assertIn("no tienes navegador", contenido.lower())

    def test_no_reescribe_si_no_ha_cambiado(self):
        with TemporaryDirectory() as workspace:
            antigravity_chat.escribir_reglas(workspace, "Ruben")
            reglas = Path(workspace) / antigravity_chat.ARCHIVO_REGLAS
            marca = reglas.stat().st_mtime_ns

            antigravity_chat.escribir_reglas(workspace, "Ruben")

            self.assertEqual(reglas.stat().st_mtime_ns, marca)

    def test_un_workspace_ilegible_no_deja_sin_conversacion(self):
        """Sin reglas responde más sosa, pero responde."""
        antigravity_chat.escribir_reglas("/no/existe/y/no/se/puede/crear", "Ruben")

    def test_el_turno_de_voz_manda_una_marca_corta(self):
        """Y no el bloque entero, que son 1.838 caracteres de peaje."""
        self.assertLess(len(antigravity_chat.MARCA_VOZ), 20)


class PrecalentarAlDespertar(unittest.IsolatedAsyncioTestCase):
    """Abrir la sesión al invocar a Vibi, no al recibir la pregunta.

    Por voz cada invocación empieza hilo nuevo, así que montar la sesión de
    forma perezosa hacía que la primera pregunta pagara los segundos enteros
    de apertura. Quien acaba de decir «Vibi» todavía tiene que hablar y
    esperar la transcripción: ahí es donde cabe ese trabajo.
    """

    async def _terminar_precalentados(self):
        for tarea in list(chat._precalentando):
            await tarea

    async def test_le_pide_al_motor_que_monte_la_sesion(self):
        motor = AsyncMock()
        motor.name = "antigravity"
        user, conversation = {"id": "u"}, {"id": "c1"}

        with patch.object(chat, "engine_for", return_value=motor):
            chat.precalentar_en_segundo_plano(user, conversation)
            await self._terminar_precalentados()

        motor.warm_session.assert_awaited_once_with(user, conversation)

    async def test_un_motor_que_no_lo_necesita_no_falla(self):
        """Claude no tiene nada que precalentar y no debe estorbar."""
        motor = AsyncMock(spec=["name", "run_turn"])
        motor.name = "anthropic"

        with patch.object(chat, "engine_for", return_value=motor):
            chat.precalentar_en_segundo_plano({"id": "u"}, {"id": "c1"})
            await self._terminar_precalentados()

    async def test_si_el_precalentado_falla_no_revienta(self):
        """El turno abrirá la sesión igualmente: esto es un adelanto, no un requisito."""
        motor = AsyncMock()
        motor.name = "antigravity"
        motor.warm_session.side_effect = RuntimeError("agy no arranca")

        with patch.object(chat, "engine_for", return_value=motor):
            chat.precalentar_en_segundo_plano({"id": "u"}, {"id": "c1"})
            await self._terminar_precalentados()


class SeleccionDeMotor(unittest.TestCase):
    def test_un_provider_desconocido_cae_en_claude(self):
        with patch.object(chat.ai_providers, "get_settings") as get_settings:
            get_settings.return_value.chat_provider = "inventado"
            self.assertEqual(chat.engine_for("u").name, "anthropic")

    def test_respeta_el_motor_elegido(self):
        with patch.object(chat.ai_providers, "get_settings") as get_settings:
            get_settings.return_value.chat_provider = "antigravity"
            self.assertEqual(chat.engine_for("u").name, "antigravity")


class _ClienteDiario:
    """Cliente que apunta en un diario común cuándo le toca a cada sesión.

    `puerta` retiene la respuesta dentro del hilo del stream, que es donde la
    retiene también el de verdad: así el turno se queda a medias y se puede
    mirar qué hace el otro mientras tanto.
    """

    def __init__(self, etiqueta, diario, puerta=None):
        self.etiqueta = etiqueta
        self.diario = diario
        self.puerta = puerta
        self.parado = []
        self._conteos = iter((0, 1))

    def stream_updates(self, cascade_id, timeout=None, skip_text=""):
        self.diario.append(f"{self.etiqueta}: stream")

        def producir():
            if self.puerta is not None:
                self.puerta.wait(5)
            yield agy_client.Update(text="ya está", done=True)

        return producir()

    def user_input_count(self, cascade_id):
        return next(self._conteos, 1)

    def stop(self, cascade_id):
        self.parado.append(cascade_id)


class TurnosQueNoSePisan(unittest.IsolatedAsyncioTestCase):
    """Dos sesiones sobre el mismo `agy` no pueden estar en turno a la vez.

    `agy` es un proceso con una sola conversación activa y la CLI manda lo
    tecleado a la última que se abriera. Como el canal de voz abre una
    conversación por invocación —29 en un día contra 32 mensajes— y la del
    chat sigue viva, el turno de una acababa entrando en la conversación de la
    otra: el acuse no llegaba nunca, moría con «agy no registró el turno
    tecleado» y el turno caía a Claude. Fue la mitad de las caídas medidas el
    17 de agosto de 2026.
    """

    def setUp(self):
        antigravity_chat._turn_locks.clear()
        self.addCleanup(antigravity_chat._turn_locks.clear)

    def _sesion(self, conversation_id, cliente):
        return antigravity_chat._LiveSession(
            conversation_id=conversation_id,
            process=None,
            client=cliente,
            cascade_id=f"cascade-{conversation_id}",
            user_id="u",
        )

    async def test_el_segundo_turno_espera_a_que_el_primero_suelte_agy(self):
        diario: list[str] = []
        puerta = threading.Event()
        self.addCleanup(puerta.set)
        chat_ = self._sesion("chat", _ClienteDiario("chat", diario, puerta))
        voz = self._sesion("voz", _ClienteDiario("voz", diario))

        def teclear(etiqueta):
            async def enviar():
                diario.append(f"{etiqueta}: teclea")

            return enviar

        with patch.object(antigravity_chat.events, "fragmento_chat", AsyncMock()):
            primero = asyncio.create_task(
                antigravity_chat._consume_turn(
                    chat_, {"id": "u"}, "chat", "t1", enviar=teclear("chat")
                )
            )
            while "chat: teclea" not in diario:
                await asyncio.sleep(0.01)

            segundo = asyncio.create_task(
                antigravity_chat._consume_turn(
                    voz, {"id": "u"}, "voz", "t2", enviar=teclear("voz")
                )
            )
            # Tiempo de sobra para colarse si no hay nada que lo frene.
            for _ in range(20):
                await asyncio.sleep(0.01)

            self.assertEqual(
                diario,
                ["chat: stream", "chat: teclea"],
                "la voz entró en agy con el turno del chat a medias",
            )

            puerta.set()
            await asyncio.gather(primero, segundo)

        self.assertEqual(
            diario,
            ["chat: stream", "chat: teclea", "voz: stream", "voz: teclea"],
        )

    async def test_montar_una_sesion_no_se_cuela_en_un_turno_en_marcha(self):
        """Abrir conversación teclea `/new`, y eso también roba la CLI.

        Es lo que hace el precalentado en cuanto dices «Vibi»: si cae mientras
        el chat está a media respuesta, el turno del chat se queda hablándole
        a una conversación que ya no está activa.
        """
        diario: list[str] = []
        puerta = threading.Event()
        self.addCleanup(puerta.set)
        chat_ = self._sesion("chat", _ClienteDiario("chat", diario, puerta))

        async def enviar():
            diario.append("chat: teclea")

        async def abrir(process):
            diario.append("voz: /new")
            return "cascade-voz"

        with (
            patch.object(antigravity_chat.events, "fragmento_chat", AsyncMock()),
            patch.object(antigravity_chat, "_abrir_conversacion", abrir),
            patch.object(antigravity_chat, "_process_for", AsyncMock(return_value=_ProcesoFalso())),
            patch.object(antigravity_chat, "escribir_reglas"),
            patch.object(antigravity_chat.files, "ensure_managed_uploads_visible"),
        ):
            turno = asyncio.create_task(
                antigravity_chat._consume_turn(
                    chat_, {"id": "u"}, "chat", "t1", enviar=enviar
                )
            )
            while "chat: teclea" not in diario:
                await asyncio.sleep(0.01)

            with TemporaryDirectory() as workspace:
                montaje = asyncio.create_task(
                    antigravity_chat._start_session(
                        "voz", Path(workspace), {"id": "u", "nombre": "Rubén"}, ()
                    )
                )
                for _ in range(20):
                    await asyncio.sleep(0.01)

                self.assertNotIn(
                    "voz: /new",
                    diario,
                    "el precalentado abrió conversación con el turno a medias",
                )

                puerta.set()
                await asyncio.gather(turno, montaje)

        self.assertEqual(diario[-1], "voz: /new")


class _ClienteMudoLaPrimeraVez:
    """Se queda callado en el primer intento y contesta en el segundo.

    Es la forma del fallo real: `agy` manda la petición a Google y esa
    petición no vuelve nunca. Cortar y repetir abre una nueva.
    """

    def __init__(self, mudo_siempre=False, texto_antes_de_callarse=""):
        self.intentos = 0
        self.entradas = 0
        self.parado = []
        self.mudo_siempre = mudo_siempre
        self.texto_antes_de_callarse = texto_antes_de_callarse
        # Suelta los hilos del stream al acabar el test. Sin esto siguen
        # durmiendo y avisan de su final sobre un bucle de eventos ya cerrado.
        self.fin = threading.Event()

    def stream_updates(self, cascade_id, timeout=None, skip_text=""):
        self.intentos += 1
        primero = self.intentos == 1

        def producir():
            if primero or self.mudo_siempre:
                if self.texto_antes_de_callarse:
                    yield agy_client.Update(
                        text=self.texto_antes_de_callarse, done=False
                    )
                # Más de lo que el turno tolera de silencio.
                self.fin.wait(1)
                return
            yield agy_client.Update(text="Ya está.", done=True)

        return producir()

    def user_input_count(self, cascade_id):
        return self.entradas

    def stop(self, cascade_id):
        self.parado.append(cascade_id)


class RepetirElTurnoAntesDeRendirse(unittest.IsolatedAsyncioTestCase):
    """Un turno mudo se repite en `agy` en vez de irse derecho a Claude.

    Medido el 17 de agosto de 2026: rendirse costaba 140 s —60 de silencio más
    lo que tardara Claude— y encima contestaba el motor que no tiene delante la
    conversación de `agy`. Repetir sale más barato que eso siempre que el
    modelo no hubiera empezado a hablar: si ya había dicho algo, repetir
    duplicaría lo dicho y entonces sí toca el fallback.
    """

    def setUp(self):
        antigravity_chat._turn_locks.clear()
        self.addCleanup(antigravity_chat._turn_locks.clear)

    def _sesion(self, cliente):
        return antigravity_chat._LiveSession(
            conversation_id="c",
            process=None,
            client=cliente,
            cascade_id="cascade-1",
            user_id="u",
        )

    async def _turno(self, cliente, sesion=None):
        tecleos: list[str] = []
        sesion = sesion or self._sesion(cliente)
        self.nuevas_conversaciones = []

        async def enviar():
            cliente.entradas += 1
            tecleos.append("teclea")

        async def abrir(process):
            # `agy` numera las suyas; aquí basta con que sea otra.
            nueva = f"cascade-{len(self.nuevas_conversaciones) + 2}"
            self.nuevas_conversaciones.append(nueva)
            # Igual que la de verdad: abrir una la deja como la activa de la
            # CLI. Sin esto el falso mentiría justo en lo que se comprueba.
            if process is not None:
                process.conversacion_activa = nueva
            return nueva

        self._abrir = abrir
        self._sesion_en_uso = sesion
        try:
            with (
                patch.object(antigravity_chat.events, "fragmento_chat", AsyncMock()),
                patch.object(antigravity_chat, "TURN_SILENCE_TIMEOUT", 0.05),
                patch.object(antigravity_chat, "TOOL_SILENCE_TIMEOUT", 0.05),
                patch.object(antigravity_chat, "_abrir_conversacion", abrir),
            ):
                respuesta = await antigravity_chat._consume_turn(
                    sesion, {"id": "u"}, "c", "t", enviar=enviar
                )
        finally:
            # Los hilos del stream tienen que morir con el bucle todavía vivo.
            cliente.fin.set()
            await asyncio.sleep(0.05)
        return respuesta, tecleos

    async def test_repite_el_turno_cuando_agy_se_queda_mudo(self):
        cliente = _ClienteMudoLaPrimeraVez()

        respuesta, tecleos = await self._turno(cliente)

        self.assertEqual(respuesta, "Ya está.")
        self.assertEqual(len(tecleos), 2, "el turno tenía que volver a entrar")
        self.assertEqual(
            cliente.parado, ["cascade-1"], "hay que cortar antes de repetir"
        )

    async def test_la_repeticion_va_a_una_conversacion_nueva(self):
        """La vieja no acepta el turno: su ejecutor sigue con el anterior.

        Medido contra el `agy` real el 17 de agosto de 2026: al repetir dentro
        de la misma conversación, la CLI contesta «SendUserMessage failed:
        executor has not processed the previous input yet» y el acuse no llega
        jamás. Cortar tampoco la libera, porque lo que está colgado es la
        petición a Google. La sesión se queda con la conversación nueva, o el
        turno siguiente volvería a la atascada.
        """
        cliente = _ClienteMudoLaPrimeraVez()
        sesion = self._sesion(cliente)

        await self._turno(cliente, sesion)

        self.assertEqual(self.nuevas_conversaciones, ["cascade-2"])
        self.assertEqual(sesion.cascade_id, "cascade-2")

    async def test_no_repite_si_el_modelo_ya_habia_empezado_a_hablar(self):
        """Repetir ahí le haría decir dos veces lo que ya había dicho."""
        cliente = _ClienteMudoLaPrimeraVez(
            mudo_siempre=True, texto_antes_de_callarse="Estoy mirándolo"
        )

        with self.assertRaises(AgyUnavailable):
            await self._turno(cliente)

        self.assertEqual(cliente.intentos, 1)

    async def test_si_la_conversacion_ya_no_es_la_activa_se_abre_otra_y_sigue(self):
        """Es el caso más recuperable de todos y era el que más caídas daba.

        Cuando la sesión descubre que su conversación ya no es la activa, el
        turno todavía NO se ha escrito en ninguna parte: repetirlo no puede
        duplicar nada ni hacer que Vibi diga dos veces lo mismo. Abrir una
        conversación —que pasa a ser la activa— y seguir cuesta décimas, frente
        a los 60 s de silencio y el cambio de motor que costaba antes.
        """
        cliente = _ClienteMudoLaPrimeraVez(mudo_siempre=False)
        # Que hable ya al primer intento: lo que falla aquí es el envío.
        cliente.intentos = 1
        sesion = self._sesion(cliente)
        sesion.process = _ProcesoFalso()
        # Otra sesión le robó la conversación activa a esta.
        sesion.process.conversacion_activa = "cascade-de-otra"

        respuesta, tecleos = await self._turno(cliente, sesion)

        self.assertEqual(respuesta, "Ya está.")
        self.assertEqual(self.nuevas_conversaciones, ["cascade-2"])
        self.assertEqual(sesion.cascade_id, "cascade-2")

    async def test_si_la_repeticion_tampoco_habla_se_rinde(self):
        cliente = _ClienteMudoLaPrimeraVez(mudo_siempre=True)

        with self.assertRaises(AgyUnavailable):
            await self._turno(cliente)

        self.assertEqual(cliente.intentos, 2, "una repetición, no más")


class ContarPorQueSeAgotoElSilencio(unittest.IsolatedAsyncioTestCase):
    """Un turno cortado tiene que decir qué estaba esperando.

    El motivo que se guardaba —«agy dejó de dar señales durante 60 s»— no
    distingue dos cosas muy distintas: una herramienta que sigue corriendo y
    una petición a Google que no vuelve con todo terminado. Averiguarlo el
    19/08/2026 costó sacar del contenedor el SQLite de la trayectoria y leer
    los pasos uno a uno. El dato está en la mano cuando salta el corte, así que
    se apunta ahí.
    """

    def test_dice_que_herramientas_seguian_en_curso(self):
        herramientas = (
            ("CORTEX_STEP_TYPE_VIEW_FILE", "CORTEX_STEP_STATUS_DONE"),
            ("CORTEX_STEP_TYPE_SEARCH_WEB", "CORTEX_STEP_STATUS_RUNNING"),
        )

        detalle = antigravity_chat._detalle_del_silencio(herramientas)

        self.assertIn("SEARCH_WEB", detalle)
        self.assertNotIn("VIEW_FILE", detalle, "esa ya había terminado")

    def test_lo_dice_tambien_cuando_no_quedaba_ninguna(self):
        """Es el caso que importa: entonces quien no vuelve es Google."""
        herramientas = (
            ("CORTEX_STEP_TYPE_VIEW_FILE", "CORTEX_STEP_STATUS_DONE"),
        )

        detalle = antigravity_chat._detalle_del_silencio(herramientas)

        self.assertIn("ninguna", detalle)

    def test_sin_pasos_no_inventa_nada(self):
        self.assertIn("ninguna", antigravity_chat._detalle_del_silencio(()))


class ApagarElNavegadorAlQuedarseSinNadie(unittest.IsolatedAsyncioTestCase):
    """El servidor MCP de Playwright no se paraba nunca.

    A `browser.mcp` solo se le llamaba con `arrancar`. Comprobado en este equipo
    el 19/08/2026: con Opera cerrado y ningún `agy` vivo, los dos procesos de
    Node seguían escuchando en el 8931, porque nadie les decía que se apagaran.

    Se apaga solo cuando no queda ni un `agy`, y no al podar uno cualquiera: el
    servidor es uno por puerto y lo comparten todos los usuarios del nodo, así
    que pararlo al caducar a uno le quitaría el navegador a otro que sigue.
    """

    def setUp(self):
        antigravity_chat._sessions.clear()
        antigravity_chat._processes.clear()
        antigravity_chat._process_touch.clear()
        self.addCleanup(antigravity_chat._sessions.clear)
        self.addCleanup(antigravity_chat._processes.clear)
        self.addCleanup(antigravity_chat._process_touch.clear)

    async def test_se_apaga_cuando_no_queda_ningun_agy(self):
        antigravity_chat._processes["u"] = _ProcesoFalso()
        antigravity_chat._process_touch["u"] = 0.0  # caducado hace años

        with patch.object(
            antigravity_chat, "apagar_playwright", AsyncMock()
        ) as apagar:
            await antigravity_chat._prune("otro")

        apagar.assert_awaited_once()

    async def test_no_se_apaga_si_queda_alguien_que_puede_navegar(self):
        antigravity_chat._processes["vivo"] = _ProcesoFalso()
        antigravity_chat._processes["caducado"] = _ProcesoFalso()
        antigravity_chat._process_touch["vivo"] = time.time()
        antigravity_chat._process_touch["caducado"] = 0.0

        with patch.object(
            antigravity_chat, "apagar_playwright", AsyncMock()
        ) as apagar:
            await antigravity_chat._prune("nadie")

        apagar.assert_not_awaited()

"""El motor Antigravity: seguir el turno por el stream y caer a Claude si falla."""
import unittest
from unittest.mock import AsyncMock, patch

from app.executors import agy_client, antigravity_chat, chat
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
                yield agy_client.Update(
                    text=texto, done=ultimo and self.done_al_final
                )

        return producir()

    def conversations(self):
        return ["cascade-1"]

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
        Morgana ya había dicho, y la cara lo locutaría otra vez.
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


class _ClienteSinConversacion:
    """Imita a `agy` cuando se ha comido el primer turno tecleado."""

    def __init__(self, aparece_tras: int):
        self.consultas = 0
        self.aparece_tras = aparece_tras

    def conversations(self):
        self.consultas += 1
        return ["cascade-1"] if self.consultas > self.aparece_tras else []


class SiElTecleoSePierde(unittest.IsolatedAsyncioTestCase):
    """La CLI se come lo que se teclea mientras aún está inicializando.

    Pasa de verdad y de forma intermitente: el arranque no siempre tarda lo
    mismo, así que esperar un rato fijo no basta. Si la conversación no
    aparece, se vuelve a teclear.
    """

    async def test_vuelve_a_teclear_y_sigue_adelante(self):
        # Tarda más de media espera, que es cuando se da por perdido el tecleo.
        cliente = _ClienteSinConversacion(aparece_tras=5)
        session = antigravity_chat._LiveSession(
            conversation_id="c", process=None, client=cliente
        )
        reintentos = []

        async def reteclear():
            reintentos.append(1)

        cascade_id = await antigravity_chat._wait_for_conversation(
            session, reintentar=reteclear, timeout=2.0
        )

        self.assertEqual(cascade_id, "cascade-1")
        self.assertEqual(len(reintentos), 1)

    async def test_si_aparece_a_la_primera_no_se_teclea_de_mas(self):
        cliente = _ClienteSinConversacion(aparece_tras=0)
        session = antigravity_chat._LiveSession(
            conversation_id="c", process=None, client=cliente
        )
        reintentos = []

        async def reteclear():
            reintentos.append(1)

        await antigravity_chat._wait_for_conversation(
            session, reintentar=reteclear, timeout=5.0
        )

        self.assertEqual(reintentos, [])


class _ProcesoFalso:
    def __init__(self):
        self.tecleado: list[str] = []
        self.muerto = False
        self.port = 1234

    def type(self, texto):
        self.tecleado.append(texto)

    def alive(self):
        return not self.muerto

    def kill(self):
        self.muerto = True


class ReutilizarElProceso(unittest.IsolatedAsyncioTestCase):
    """Cerrar una conversación no puede matar a `agy`.

    El canal de voz reinicia la conversación cada vez que invocas a Morgana, y
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
        """Y le pide una conversación limpia con /new en vez de reiniciarlo."""
        proceso = _ProcesoFalso()
        antigravity_chat._processes["u"] = proceso

        reutilizado, _ = await antigravity_chat._process_for(
            {"id": "u", "nombre": "R"}, workspace="/tmp"
        )

        self.assertIs(reutilizado, proceso)
        self.assertIn("/new", proceso.tecleado)


class QuedarseConLaConversacionNueva(unittest.IsolatedAsyncioTestCase):
    """Tras `/new` conviven varias conversaciones en el mismo proceso.

    Coger «la primera» devolvía la vieja, y Morgana habría seguido leyendo el
    hilo que el usuario acababa de cerrar.
    """

    async def test_ignora_las_que_ya_existian(self):
        class _Cliente:
            def __init__(self):
                self.veces = 0

            def conversations(self):
                self.veces += 1
                if self.veces < 2:
                    return ["vieja"]
                return ["vieja", "nueva"]

        session = antigravity_chat._LiveSession(
            conversation_id="c", process=None, client=_Cliente()
        )

        cascade_id = await antigravity_chat._wait_for_conversation(
            session, conocidas={"vieja"}, timeout=5.0
        )

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
        ), patch.object(chat.db, "list_context_messages", return_value=[]):
            result = await chat._run_with_fallback(
                roto, {"id": "u", "nombre": "R"}, {"id": "c"}, "hola", (), "t", (), False
            )

        self.assertIn("Hace sol.", result.response)
        self.assertIn("no estaba disponible", result.response)
        roto.close_session.assert_awaited_once_with("c")

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


class SeleccionDeMotor(unittest.TestCase):
    def test_un_provider_desconocido_cae_en_claude(self):
        with patch.object(chat.ai_providers, "get_settings") as get_settings:
            get_settings.return_value.chat_provider = "inventado"
            self.assertEqual(chat.engine_for("u").name, "anthropic")

    def test_respeta_el_motor_elegido(self):
        with patch.object(chat.ai_providers, "get_settings") as get_settings:
            get_settings.return_value.chat_provider = "antigravity"
            self.assertEqual(chat.engine_for("u").name, "antigravity")

"""Mercury: el cliente, el interruptor de motor principal y el bucle de tools."""
import json
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import httpx

from app import ai_providers, db, mercury
from app.config import settings
from app.executors import chat, mercury_chat


def _sse(*trozos: dict) -> bytes:
    lineas = [f"data: {json.dumps(trozo)}\n\n" for trozo in trozos]
    lineas.append("data: [DONE]\n\n")
    return "".join(lineas).encode()


def _delta(**delta) -> dict:
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}


class _ConCliente:
    """Sustituye el cliente httpx de Mercury por uno con transporte falso."""

    def usar(self, manejador) -> list[dict]:
        pedidos: list[dict] = []

        def registrar(peticion: httpx.Request) -> httpx.Response:
            pedidos.append(json.loads(peticion.content))
            return manejador(peticion)

        falso = httpx.AsyncClient(
            base_url="https://mercury.test/v1",
            transport=httpx.MockTransport(registrar),
        )
        parche = patch.object(mercury, "_cliente", falso)
        parche.start()
        self.addCleanup(parche.stop)
        return pedidos


class ClienteTests(_ConCliente, IsolatedAsyncioTestCase):
    def setUp(self):
        parche = patch.object(settings, "mercury_api_key", "sk-prueba-mercury")
        parche.start()
        self.addCleanup(parche.stop)

    async def test_temperatura_cero_se_acota_al_minimo_que_acepta(self):
        """Vibi pide 0 para clasificar; Mercury solo admite de 0,5 a 1."""
        pedidos = self.usar(
            lambda _: httpx.Response(
                200, json={"choices": [{"message": {"content": " {\"via\": \"rapida\"} "}}]}
            )
        )

        texto = await mercury.completar(
            [{"role": "user", "content": "hola"}],
            max_tokens=180,
            temperature=0,
            json_mode=True,
        )

        self.assertEqual(texto, '{"via": "rapida"}')
        self.assertEqual(pedidos[0]["temperature"], 0.5)
        self.assertEqual(pedidos[0]["max_completion_tokens"], 180)
        self.assertEqual(pedidos[0]["response_format"], {"type": "json_object"})
        # Con topes cortos, razonar se comería la respuesta.
        self.assertEqual(pedidos[0]["reasoning_effort"], "instant")

    async def test_un_cuelgue_suelto_se_reintenta_una_vez(self):
        intentos = []

        def manejador(peticion):
            intentos.append(1)
            if len(intentos) == 1:
                raise httpx.ReadTimeout("colgado", request=peticion)
            return httpx.Response(200, json={"choices": [{"message": {"content": "hola"}}]})

        self.usar(manejador)

        texto = await mercury.completar([{"role": "user", "content": "x"}], max_tokens=10)

        self.assertEqual(texto, "hola")
        self.assertEqual(len(intentos), 2)

    async def test_un_error_de_la_api_se_explica(self):
        self.usar(lambda _: httpx.Response(401, json={"error": "clave mala"}))

        with self.assertRaisesRegex(mercury.MercuryError, "401"):
            await mercury.completar([{"role": "user", "content": "x"}], max_tokens=10)

    async def test_el_stream_cose_las_llamadas_troceadas(self):
        cuerpo = _sse(
            _delta(content="Voy "),
            _delta(content="a mirarlo."),
            _delta(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "mcp__vibi__tasks_list", "arguments": '{"lim'},
                    }
                ]
            ),
            _delta(tool_calls=[{"index": 0, "function": {"arguments": 'it": 3}'}}]),
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        )
        self.usar(lambda _: httpx.Response(200, content=cuerpo))

        vuelta = mercury.Vuelta()
        eventos = [
            evento
            async for evento in mercury.conversar(
                [{"role": "user", "content": "x"}], [{"type": "function"}], vuelta
            )
        ]

        self.assertEqual(vuelta.texto, "Voy a mirarlo.")
        self.assertEqual(vuelta.motivo, "tool_calls")
        self.assertEqual(len(vuelta.llamadas), 1)
        self.assertEqual(vuelta.llamadas[0].nombre, "mcp__vibi__tasks_list")
        self.assertEqual(json.loads(vuelta.llamadas[0].argumentos), {"limit": 3})
        self.assertIn("mcp__vibi__tasks_list", [e.herramienta for e in eventos])


class InterruptorTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        for parche in (
            patch.object(settings, "db_path", str(Path(self.tempdir.name) / "v.db")),
            patch.object(settings, "mercury_api_key", "sk-prueba-mercury"),
            patch.object(settings, "mercury_principal", True),
        ):
            parche.start()
            self.addCleanup(parche.stop)
        db.init_db()
        self.user = db.get_or_create_user("ana")
        ai_providers.save_settings(
            self.user["id"],
            ai_providers.AISettings(
                chat_provider="antigravity",
                chat_model="",
                tools_provider="groq",
                tools_model="openai/gpt-oss-120b",
                speech_provider="groq",
                speech_model="whisper-large-v3-turbo",
                agent_provider="anthropic",
                agent_model="claude-sonnet-5",
            ),
        )

    def test_mercury_contesta_el_chat_aunque_estuviera_elegido_agy(self):
        self.assertIs(chat.engine_for(self.user["id"]), mercury_chat.ENGINE)
        carril = ai_providers.resolve_lane(self.user["id"], "tools")
        self.assertEqual((carril.provider, carril.model), ("mercury", "mercury-2.5"))

    def test_voz_y_agente_no_cambian(self):
        configurado = ai_providers.get_settings(self.user["id"])
        self.assertEqual(configurado.speech_provider, "groq")
        self.assertEqual(configurado.agent_provider, "anthropic")

    def test_ajustes_muestra_lo_guardado_y_lo_efectivo_aparte(self):
        """Ajustes reenvía lo que lee: no puede pisar la elección del usuario."""
        publico = ai_providers.public_settings(self.user["id"])
        self.assertEqual(publico["chat_provider"], "antigravity")
        self.assertTrue(publico["mercury_principal"])
        self.assertEqual(publico["effective"]["chat"]["provider"], "mercury")

    def test_sin_clave_no_hay_mercury(self):
        with patch.object(settings, "mercury_api_key", ""):
            self.assertEqual(
                ai_providers.get_settings(self.user["id"]).chat_provider, "antigravity"
            )


def _vuelta_falsa(guion: list[mercury.Vuelta], vistos: list[list[dict]]):
    async def conversar(mensajes, herramientas, vuelta, **_):
        vistos.append([dict(m) for m in mensajes])
        siguiente = guion.pop(0)
        vuelta.texto = siguiente.texto
        vuelta.llamadas = siguiente.llamadas
        for llamada in siguiente.llamadas:
            yield mercury.Evento(herramienta=llamada.nombre)
        if siguiente.texto:
            yield mercury.Evento(texto=siguiente.texto)

    return conversar


class MotorTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = {"id": "u1", "nombre": "Ana", "is_admin": False}
        self.conversation = {"id": "c1"}
        catalogo = [
            {
                "id": "tasks.list",
                "scope": "system",
                "name": "Ver tareas",
                "description": "Lista las tareas.",
                "primitive_id": "tasks.list",
                "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
                "enabled": True,
            }
        ]
        for parche in (
            patch.object(mercury_chat.tools, "list_catalog", return_value=catalogo),
            patch.object(mercury_chat, "_sistema", AsyncMock(return_value=None)),
            patch.object(mercury_chat.events, "fragmento_chat", AsyncMock()),
            patch.object(mercury_chat.events, "progreso_chat", AsyncMock()),
        ):
            parche.start()
            self.addCleanup(parche.stop)

    async def test_ejecuta_la_tool_y_le_devuelve_el_resultado(self):
        vistos: list[list[dict]] = []
        guion = [
            mercury.Vuelta(
                llamadas=[
                    mercury.LlamadaHerramienta("c1", "mcp__vibi__tasks_list", '{"limit": 2}')
                ]
            ),
            mercury.Vuelta(texto="Tienes una tarea: compilar."),
        ]
        ejecutar = AsyncMock(return_value={"result": {"tasks": ["compilar"]}})
        with patch.object(mercury, "conversar", _vuelta_falsa(guion, vistos)), patch.object(
            mercury_chat.tools, "execute", ejecutar
        ):
            resultado = await mercury_chat.ENGINE.run_turn(
                self.user,
                self.conversation,
                "¿qué tareas tengo?",
                (),
                "t1",
                ({"role": "user", "content": "hola"}, {"role": "assistant", "content": "dime"}),
                False,
            )

        self.assertEqual(resultado.response, "Tienes una tarea: compilar.")
        ejecutar.assert_awaited_once_with("tasks.list", self.user, {"limit": 2})
        segunda = vistos[1]
        # El historial va como mensajes, no pegado en el texto.
        self.assertEqual([m["role"] for m in segunda[:3]], ["system", "user", "assistant"])
        self.assertEqual(segunda[-1]["role"], "tool")
        self.assertIn("compilar", segunda[-1]["content"])

    async def test_argumentos_rotos_vuelven_como_error_sin_ejecutar(self):
        vistos: list[list[dict]] = []
        guion = [
            mercury.Vuelta(
                llamadas=[mercury.LlamadaHerramienta("c1", "mcp__vibi__tasks_list", "{mal")]
            ),
            mercury.Vuelta(texto="No pude."),
        ]
        ejecutar = AsyncMock()
        with patch.object(mercury, "conversar", _vuelta_falsa(guion, vistos)), patch.object(
            mercury_chat.tools, "execute", ejecutar
        ):
            await mercury_chat.ENGINE.run_turn(
                self.user, self.conversation, "x", (), "t1", (), False
            )

        ejecutar.assert_not_awaited()
        self.assertTrue(vistos[1][-1]["content"].startswith("ERROR"))

    async def test_las_imagenes_no_le_llegan(self):
        vistos: list[list[dict]] = []
        guion = [
            mercury.Vuelta(
                llamadas=[mercury.LlamadaHerramienta("c1", "mcp__vibi__tasks_list", "{}")]
            ),
            mercury.Vuelta(texto="Vale."),
        ]
        resultado = {"result": {"ok": True, "image": {"data": "A" * 5000}}}
        with patch.object(mercury, "conversar", _vuelta_falsa(guion, vistos)), patch.object(
            mercury_chat.tools, "execute", AsyncMock(return_value=resultado)
        ):
            await mercury_chat.ENGINE.run_turn(
                self.user, self.conversation, "x", (), "t1", (), False
            )

        contenido = vistos[1][-1]["content"]
        self.assertNotIn("AAAA", contenido)
        self.assertIn("devices_ui_snapshot", contenido)

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from app.core import messages
from app.executors.chat_engine import ChatResult
from app.tasks import ResolucionProyecto


class MessageCoreTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = {"id": "u1", "nombre": "Rubén"}

    async def test_via_rapida_devuelve_respuesta_del_chat(self):
        with patch(
            "app.core.messages.chat.respond",
            AsyncMock(return_value=ChatResult(response="Respuesta rápida")),
        ) as responder, patch("app.core.messages.db.log_event"):
            result = await messages.procesar_mensaje(
                self.user, "¿Qué es una PWA?", canal="pwa"
            )

        self.assertEqual(result.via, "rapida")
        self.assertEqual(result.respuesta, "Respuesta rápida")
        self.assertIsNone(result.task)
        responder.assert_awaited_once_with(
            self.user,
            "¿Qué es una PWA?",
            "pwa",
            None,
            attached_tool_ids=(),
            voz=False,
            conversation_id=None,
        )

    async def test_via_agentica_resuelve_y_encola_en_el_core(self):
        resolucion = ResolucionProyecto(
            "ok", workspace="C:/workspace/u1/vibi", proyectos=("vibi",)
        )
        task = {"id": "t1"}
        with patch(
            "app.core.messages.tasks.resolver_proyecto", return_value=resolucion
        ), patch(
            "app.core.messages.tasks.encolar_tarea", AsyncMock(return_value=task)
        ) as encolar, patch("app.core.messages.db.log_event"):
            result = await messages.procesar_encargo(
                self.user,
                "Añade la PWA en vibi",
                "vibi",
                canal="telegram",
                modelo="claude-opus-4-8",
            )

        self.assertEqual(result.via, "agentica")
        self.assertEqual(result.task, task)
        self.assertEqual(result.resolucion, resolucion)
        encolar.assert_awaited_once_with(
            "u1",
            "Rubén",
            "Añade la PWA en vibi",
            "C:/workspace/u1/vibi",
            "claude-opus-4-8",
        )

    async def test_via_agentica_usa_modelo_personal_por_defecto(self):
        resolucion = ResolucionProyecto(
            "ok", workspace="C:/workspace/u1/vibi", proyectos=("vibi",)
        )
        with patch(
            "app.core.messages.tasks.resolver_proyecto", return_value=resolucion
        ), patch(
            "app.core.messages.tasks.encolar_tarea",
            AsyncMock(return_value={"id": "t1"}),
        ) as encolar, patch(
            "app.core.messages.ai_providers.get_settings",
            return_value=SimpleNamespace(agent_model="claude-haiku-4-5"),
        ), patch("app.core.messages.db.log_event"):
            await messages.procesar_encargo(
                self.user, "Haz el cambio en vibi", "vibi", canal="pwa"
            )

        encolar.assert_awaited_once_with(
            "u1",
            "Rubén",
            "Haz el cambio en vibi",
            "C:/workspace/u1/vibi",
            "claude-haiku-4-5",
        )

    async def test_proyecto_ambiguo_se_devuelve_sin_encolar(self):
        resolucion = ResolucionProyecto(
            "requiere_proyecto", proyectos=("vibi", "otro")
        )
        with patch(
            "app.core.messages.tasks.resolver_proyecto", return_value=resolucion
        ), patch(
            "app.core.messages.tasks.encolar_tarea", AsyncMock()
        ) as encolar, patch("app.core.messages.db.log_event"):
            result = await messages.procesar_encargo(
                self.user, "Haz el cambio", None, canal="api"
            )

        self.assertEqual(result.via, "agentica")
        self.assertIsNone(result.task)
        self.assertEqual(result.resolucion.estado, "requiere_proyecto")
        encolar.assert_not_awaited()

    async def test_lectura_de_archivo_responde_con_su_contenido(self):
        file = {
            "id": "f1",
            "name": "matricula.pdf",
            "download_url": "/api/archivos/f1/contenido",
        }
        with patch(
            "app.core.messages.chat.respond",
            AsyncMock(
                return_value=ChatResult(
                    response="Es una matrícula de cuarto curso.",
                    artifacts=(file,),
                )
            ),
        ) as responder, patch("app.core.messages.db.log_event"):
            result = await messages.procesar_mensaje(
                self.user,
                "¿Qué pone en mi matrícula?",
                canal="pwa",
                client_ref="c1",
                tool_ids=("files.read",),
            )

        self.assertEqual(result.via, "herramienta")
        self.assertEqual(result.respuesta, "Es una matrícula de cuarto curso.")
        self.assertEqual(result.artifacts, (file,))
        responder.assert_awaited_once_with(
            self.user,
            "¿Qué pone en mi matrícula?",
            "pwa",
            "c1",
            attached_tool_ids=("files.read",),
            voz=False,
            conversation_id=None,
        )

    async def test_seleccion_pendiente_va_directa_al_encargo(self):
        resolucion = ResolucionProyecto(
            "ok", workspace="C:/workspace/u1/vibi", proyectos=("vibi",)
        )
        with patch(
            "app.core.messages.tasks.resolver_proyecto", return_value=resolucion
        ), patch(
            "app.core.messages.tasks.encolar_tarea",
            AsyncMock(return_value={"id": "t1"}),
        ), patch("app.core.messages.db.log_event"):
            result = await messages.procesar_encargo(
                self.user, "Haz el cambio", "vibi", canal="telegram"
            )

        self.assertEqual(result.task["id"], "t1")

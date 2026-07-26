from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from app.core import messages
from app.tasks import ResolucionProyecto


class MessageCoreTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = {"id": "u1", "nombre": "Rubén"}
        self.active_conversation = patch(
            "app.core.messages.db.get_active_conversation", return_value=None
        )
        self.active_conversation.start()
        self.addCleanup(self.active_conversation.stop)
        self.ai_settings = patch(
            "app.core.messages.ai_providers.get_settings",
            return_value=SimpleNamespace(agent_model="claude-sonnet-5"),
        )
        self.ai_settings.start()
        self.addCleanup(self.ai_settings.stop)

    async def test_via_rapida_devuelve_respuesta_del_chat(self):
        with patch(
            "app.core.messages.router.clasificar",
            AsyncMock(return_value={"via": "rapida", "proyecto": None}),
        ), patch(
            "app.core.messages.groq_chat.responder",
            AsyncMock(return_value="Respuesta rápida"),
        ) as responder, patch("app.core.messages.db.log_event"):
            result = await messages.procesar_mensaje(
                self.user, "¿Qué es una PWA?", canal="pwa"
            )

        self.assertEqual(result.via, "rapida")
        self.assertEqual(result.respuesta, "Respuesta rápida")
        self.assertIsNone(result.task)
        responder.assert_awaited_once_with(
            "u1", "Rubén", "¿Qué es una PWA?", "pwa", None
        )

    async def test_via_agentica_resuelve_y_encola_en_el_core(self):
        resolucion = ResolucionProyecto(
            "ok", workspace="C:/workspace/u1/morgana", proyectos=("morgana",)
        )
        task = {"id": "t1"}
        with patch(
            "app.core.messages.router.clasificar",
            AsyncMock(return_value={"via": "agentica", "proyecto": "morgana"}),
        ), patch(
            "app.core.messages.tasks.resolver_proyecto", return_value=resolucion
        ), patch(
            "app.core.messages.tasks.encolar_tarea", AsyncMock(return_value=task)
        ) as encolar, patch("app.core.messages.db.log_event"):
            result = await messages.procesar_mensaje(
                self.user,
                "Añade la PWA en morgana",
                canal="telegram",
                modelo="claude-opus-4-8",
            )

        self.assertEqual(result.via, "agentica")
        self.assertEqual(result.task, task)
        self.assertEqual(result.resolucion, resolucion)
        encolar.assert_awaited_once_with(
            "u1",
            "Rubén",
            "Añade la PWA en morgana",
            "C:/workspace/u1/morgana",
            "claude-opus-4-8",
        )

    async def test_via_agentica_usa_modelo_personal_por_defecto(self):
        resolucion = ResolucionProyecto(
            "ok", workspace="C:/workspace/u1/morgana", proyectos=("morgana",)
        )
        with patch(
            "app.core.messages.router.clasificar",
            AsyncMock(return_value={"via": "agentica", "proyecto": "morgana"}),
        ), patch(
            "app.core.messages.tasks.resolver_proyecto", return_value=resolucion
        ), patch(
            "app.core.messages.tasks.encolar_tarea",
            AsyncMock(return_value={"id": "t1"}),
        ) as encolar, patch(
            "app.core.messages.ai_providers.get_settings",
            return_value=SimpleNamespace(agent_model="claude-haiku-4-5"),
        ), patch("app.core.messages.db.log_event"):
            await messages.procesar_mensaje(
                self.user, "Haz el cambio en morgana", canal="pwa"
            )

        encolar.assert_awaited_once_with(
            "u1",
            "Rubén",
            "Haz el cambio en morgana",
            "C:/workspace/u1/morgana",
            "claude-haiku-4-5",
        )

    async def test_proyecto_ambiguo_se_devuelve_sin_encolar(self):
        resolucion = ResolucionProyecto(
            "requiere_proyecto", proyectos=("morgana", "otro")
        )
        with patch(
            "app.core.messages.router.clasificar",
            AsyncMock(return_value={"via": "agentica", "proyecto": None}),
        ), patch(
            "app.core.messages.tasks.resolver_proyecto", return_value=resolucion
        ), patch(
            "app.core.messages.tasks.encolar_tarea", AsyncMock()
        ) as encolar, patch("app.core.messages.db.log_event"):
            result = await messages.procesar_mensaje(
                self.user, "Haz el cambio", canal="api"
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
        classification = {
            "via": "herramienta",
            "proyecto": None,
            "herramienta": "files.read",
            "argumentos": {"query": "matrícula informática"},
        }
        with patch(
            "app.core.messages.router.clasificar",
            AsyncMock(return_value=classification),
        ), patch(
            "app.core.messages.tools.execute",
            AsyncMock(
                return_value={
                    "result": {
                        "files": [file],
                        "content": "Matrícula de Ingeniería Informática",
                    }
                }
            ),
        ), patch(
            "app.core.messages.groq_chat.responder",
            AsyncMock(return_value="Es una matrícula de cuarto curso."),
        ) as responder, patch("app.core.messages.db.log_event"):
            result = await messages.procesar_mensaje(
                self.user,
                "¿Qué pone en mi matrícula?",
                canal="pwa",
                client_ref="c1",
            )

        self.assertEqual(result.via, "herramienta")
        self.assertEqual(result.respuesta, "Es una matrícula de cuarto curso.")
        self.assertEqual(result.artifacts, (file,))
        responder.assert_awaited_once_with(
            "u1",
            "Rubén",
            "¿Qué pone en mi matrícula?",
            "pwa",
            "c1",
            document_context=(
                "matricula.pdf",
                "Matrícula de Ingeniería Informática",
            ),
            purpose="tools",
        )

    async def test_seleccion_pendiente_no_vuelve_a_clasificar(self):
        resolucion = ResolucionProyecto(
            "ok", workspace="C:/workspace/u1/morgana", proyectos=("morgana",)
        )
        with patch(
            "app.core.messages.tasks.resolver_proyecto", return_value=resolucion
        ), patch(
            "app.core.messages.tasks.encolar_tarea",
            AsyncMock(return_value={"id": "t1"}),
        ), patch("app.core.messages.router.clasificar", AsyncMock()) as clasificar, patch(
            "app.core.messages.db.log_event"
        ):
            result = await messages.procesar_encargo(
                self.user, "Haz el cambio", "morgana", canal="telegram"
            )

        self.assertEqual(result.task["id"], "t1")
        clasificar.assert_not_awaited()

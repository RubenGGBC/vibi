from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from app.core import messages
from app.tasks import ResolucionProyecto


class MessageCoreTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = {"id": "u1", "nombre": "Rubén"}

    async def test_via_rapida_devuelve_respuesta_del_chat(self):
        with patch(
            "app.core.messages.router.clasificar",
            AsyncMock(return_value={"via": "rapida", "proyecto": None}),
        ), patch(
            "app.core.messages.groq_chat.responder",
            AsyncMock(return_value="Respuesta rápida"),
        ) as responder, patch("app.core.messages.db.log_event"):
            result = await messages.procesar_mensaje(
                self.user, "¿Qué es una PWA?", canal="api"
            )

        self.assertEqual(result.via, "rapida")
        self.assertEqual(result.respuesta, "Respuesta rápida")
        self.assertIsNone(result.task)
        responder.assert_awaited_once_with("u1", "Rubén", "¿Qué es una PWA?")

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

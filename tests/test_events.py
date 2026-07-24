import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth, db, events, tasks
from app.config import settings
from app.main import create_app


class FakeSocket:
    def __init__(self):
        self.accept = AsyncMock()
        self.send_json = AsyncMock()


class ConnectionManagerTests(IsolatedAsyncioTestCase):
    async def test_envia_solo_a_conexiones_del_usuario(self):
        manager = events.ConnectionManager()
        first = FakeSocket()
        other = FakeSocket()
        await manager.connect("u1", "d1", first)
        await manager.connect("u2", "d2", other)

        await manager.send("u1", {"tipo": "notificacion", "texto": "hola"})

        first.send_json.assert_awaited_once()
        other.send_json.assert_not_awaited()

    async def test_elimina_socket_que_falla(self):
        manager = events.ConnectionManager()
        broken = FakeSocket()
        broken.send_json.side_effect = RuntimeError("cerrado")
        await manager.connect("u1", "d1", broken)

        await manager.send("u1", {"tipo": "notificacion", "texto": "hola"})

        self.assertNotIn(
            broken, manager.connections.get("u1", {}).get("d1", set())
        )


class TaskEventTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        root = Path(self.tempdir.name)
        self.db_patch = patch.object(settings, "db_path", str(root / "morgana.db"))
        self.ws_patch = patch.object(settings, "workspace_root", str(root / "workspace"))
        self.db_patch.start()
        self.ws_patch.start()
        db.init_db()
        self.user = db.get_or_create_user("ruben")
        self.project = root / "workspace" / self.user["id"] / "morgana"
        self.project.mkdir(parents=True)

    async def _cleanup(self):
        self.db_patch.stop()
        self.ws_patch.stop()
        self.tempdir.cleanup()

    async def test_creacion_emite_tarea_completa(self):
        observer = AsyncMock()
        with patch.object(tasks, "_observadores_tareas", []):
            tasks.registrar_observador_tareas(observer)
            task = await tasks.encolar_tarea(
                self.user["id"], "ruben", "haz algo", str(self.project)
            )

        observer.assert_awaited_once()
        user_id, emitted = observer.await_args.args
        self.assertEqual(user_id, self.user["id"])
        self.assertEqual(emitted["id"], task["id"])
        self.assertEqual(emitted["estado"], "pendiente")
        self.assertIn("actualizado_en", emitted)

    async def test_rechazo_persiste_y_emite_estado_nuevo(self):
        task = db.create_task(self.user["id"], "haz algo", str(self.project))
        db.update_task(task["id"], estado="esperando_aprobacion")
        observer = AsyncMock()
        notifier = AsyncMock()
        with patch.object(tasks, "_observadores_tareas", []), patch.object(
            tasks, "_notificadores", []
        ):
            tasks.registrar_observador_tareas(observer)
            tasks.registrar_notificador(notifier)
            changed = await tasks.rechazar_tarea(task["id"])

        self.assertTrue(changed)
        self.assertEqual(db.get_task(task["id"])["estado"], "rechazada")
        self.assertEqual(observer.await_args.args[1]["estado"], "rechazada")
        self.assertEqual(notifier.await_args.args[2], task["id"])
        self.assertFalse(notifier.await_args.args[3])


class WebSocketAuthTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.patches = [
            patch.object(settings, "db_path", str(Path(self.tempdir.name) / "db.sqlite")),
            patch.object(
                settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        db.init_db()
        self.user = db.get_or_create_user("ruben")
        self.client = TestClient(create_app(start_background=False))
        self.addCleanup(self.client.close)

    def test_rechaza_token_invalido(self):
        with self.assertRaises(WebSocketDisconnect) as captured:
            with self.client.websocket_connect("/api/eventos") as socket:
                socket.send_json(
                    {
                        "token": "invalido",
                        "device_id": "test-device",
                        "device_type": "pc",
                    }
                )
                socket.receive_json()
        self.assertEqual(captured.exception.code, 4401)

    def test_acepta_token_valido(self):
        token = auth.create_access_token(self.user["id"])
        with self.client.websocket_connect("/api/eventos") as socket:
            socket.send_json(
                {
                    "token": token,
                    "device_id": "test-device",
                    "device_type": "pc",
                }
            )
            self.assertEqual(socket.receive_json()["tipo"], "conexion_lista")
            self.assertIn(self.user["id"], events.manager.connections)

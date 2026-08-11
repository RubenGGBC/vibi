import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import auth, db
from app.config import settings
from app.core.messages import ResultadoMensaje
from app.main import create_app
from app.tasks import ResolucionProyecto


class ApiTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.root = root
        self.patches = [
            patch.object(settings, "db_path", str(root / "morgana.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
            patch.object(
                settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"
            ),
        ]
        for setting_patch in self.patches:
            setting_patch.start()
            self.addCleanup(setting_patch.stop)

        db.init_db()
        self.user = db.get_or_create_user("ruben")
        db.set_password_hash(self.user["id"], auth.hash_password("correcta"))
        self.other = db.get_or_create_user("otra")
        self.workspace = root / "workspace" / self.user["id"] / "morgana"
        self.workspace.mkdir(parents=True)
        self.client = TestClient(
            create_app(start_background=False, frontend_dir=root / "missing-dist")
        )
        self.addCleanup(self.client.close)
        self.token = self.client.post(
            "/api/auth/login",
            json={"nombre": "ruben", "contraseña": "correcta"},
        ).json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_login_rechaza_credenciales_invalidas(self):
        response = self.client.post(
            "/api/auth/login",
            json={"nombre": "ruben", "contraseña": "incorrecta"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Credenciales inválidas"})

    def test_endpoint_protegido_exige_bearer(self):
        response = self.client.get("/api/yo")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Autenticación requerida"})

    def test_yo_devuelve_solo_identidad_publica(self):
        response = self.client.get("/api/yo", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"id": self.user["id"], "nombre": "ruben"}
        )

    def test_configuracion_ia_guarda_claves_sin_exponerlas(self):
        anthropic_key = "sk-ant-clave-personal-de-ruben"
        with patch.object(settings, "anthropic_api_key", ""), patch.object(
            settings, "groq_api_key", ""
        ):
            response = self.client.put(
                "/api/configuracion/ia",
                headers=self.headers,
                json={
                    "chat_provider": "anthropic",
                    "chat_model": "llama-personal",
                    "tools_provider": "anthropic",
                    "tools_model": "claude-haiku-4-5",
                    "speech_provider": "groq",
                    "speech_model": "whisper-large-v3-turbo",
                    "agent_provider": "anthropic",
                    "agent_model": "claude-sonnet-5",
                    "anthropic_api_key": anthropic_key,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["tools_model"], "claude-haiku-4-5")
        self.assertEqual(
            payload["credentials"]["anthropic"],
            {"configured": True, "source": "personal"},
        )
        self.assertNotIn(anthropic_key, response.text)
        self.assertNotIn(
            anthropic_key,
            db.get_provider_credential(self.user["id"], "anthropic"),
        )

    def test_lista_tareas_del_usuario_con_filtros_y_orden(self):
        first = db.create_task(self.user["id"], "primera", "C:/ws/alpha")
        second = db.create_task(self.user["id"], "segunda", "C:/ws/beta")
        db.update_task(first["id"], estado="completada")
        db.update_task(second["id"], estado="esperando_aprobacion")
        db.create_task(self.other["id"], "secreta", "C:/ws/alpha")

        response = self.client.get(
            "/api/tareas?estado=esperando_aprobacion&proyecto=beta&limite=5",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        tasks = response.json()
        self.assertEqual([task["id"] for task in tasks], [second["id"]])
        self.assertEqual(tasks[0]["proyecto"], "beta")
        self.assertNotIn("secreta", repr(tasks))

    def test_actividad_es_privada_paginada_y_sin_payload_crudo(self):
        older = db.create_task(
            self.user["id"], "prompt antiguo secreto", str(self.workspace)
        )
        newer = db.create_task(
            self.user["id"], "prompt reciente secreto", str(self.workspace)
        )
        foreign = db.create_task(
            self.other["id"], "prompt ajeno", str(self.root / "foreign")
        )
        db.log_event(
            "tarea_creada",
            self.user["id"],
            task_id=older["id"],
            prompt=older["prompt"],
            workspace=older["workspace"],
        )
        db.log_event(
            "tarea_creada",
            self.user["id"],
            task_id=newer["id"],
            prompt=newer["prompt"],
            workspace=newer["workspace"],
        )
        db.log_event(
            "tarea_creada",
            self.other["id"],
            task_id=foreign["id"],
            prompt=foreign["prompt"],
            workspace=foreign["workspace"],
        )

        response = self.client.get(
            "/api/actividad?limite=1&categoria=tareas",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["eventos"]), 1)
        self.assertEqual(payload["eventos"][0]["titulo"], "Tarea creada")
        self.assertEqual(
            payload["eventos"][0]["enlace"], f"/tareas/{newer['id']}"
        )
        self.assertIsNotNone(payload["siguiente_cursor"])
        self.assertEqual(payload["resumen"]["tareas_activas"], 2)
        self.assertEqual(
            payload["resumen"]["almacenamiento_cuota_bytes"],
            settings.file_user_quota_bytes,
        )
        self.assertNotIn("prompt reciente secreto", response.text)
        self.assertNotIn("prompt ajeno", response.text)
        self.assertNotIn("workspace", response.text)

    def test_actividad_rechaza_categoria_desconocida(self):
        response = self.client.get(
            "/api/actividad?categoria=desconocida", headers=self.headers
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"error": "Parámetros inválidos"})

    def test_detalle_no_revela_tarea_de_otro_usuario(self):
        task = db.create_task(self.other["id"], "secreta", "C:/ws/alpha")
        response = self.client.get(
            f"/api/tareas/{task['id']}", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Tarea no encontrada"})

    def test_aprobar_valida_estado_y_reutiliza_orquestador(self):
        task = db.create_task(self.user["id"], "cambio", "C:/ws/alpha")
        db.update_task(task["id"], estado="esperando_aprobacion", plan="plan")
        with patch("app.api.tasks.aprobar_tarea", AsyncMock(return_value=True)) as approve:
            response = self.client.post(
                f"/api/tareas/{task['id']}/aprobar", headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        approve.assert_awaited_once_with(task["id"])

    def test_aprobar_rechaza_estado_incorrecto(self):
        task = db.create_task(self.user["id"], "cambio", "C:/ws/alpha")
        response = self.client.post(
            f"/api/tareas/{task['id']}/aprobar", headers=self.headers
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(), {"error": "La tarea no espera aprobación"}
        )

    def test_reintentar_error_crea_un_intento_nuevo_y_auditable(self):
        original = db.create_task(
            self.user["id"],
            "Corrige el despliegue",
            str(self.workspace),
            "claude-haiku-4-5",
        )
        db.update_task(original["id"], estado="error", resultado="Fallo de red")

        response = self.client.post(
            f"/api/tareas/{original['id']}/reintentar", headers=self.headers
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        retried = payload["task"]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source_task_id"], original["id"])
        self.assertNotEqual(retried["id"], original["id"])
        self.assertEqual(retried["prompt"], original["prompt"])
        self.assertEqual(retried["modelo"], "claude-haiku-4-5")
        self.assertEqual(retried["estado"], "pendiente")
        self.assertEqual(db.get_task(original["id"])["estado"], "error")
        audit, _ = db.list_events_for_user(
            self.user["id"], 10, None, ("tarea_reintentada",)
        )
        self.assertEqual(len(audit), 1)
        self.assertEqual(
            json.loads(audit[0]["payload"]),
            {"source_task_id": original["id"], "task_id": retried["id"]},
        )

    def test_reintentar_rechaza_estado_incorrecto_y_tarea_ajena(self):
        pending = db.create_task(
            self.user["id"], "Sigue pendiente", str(self.workspace)
        )
        foreign = db.create_task(
            self.other["id"], "No revelar", str(self.root / "foreign")
        )
        db.update_task(foreign["id"], estado="error")

        wrong_state = self.client.post(
            f"/api/tareas/{pending['id']}/reintentar", headers=self.headers
        )
        hidden = self.client.post(
            f"/api/tareas/{foreign['id']}/reintentar", headers=self.headers
        )

        self.assertEqual(wrong_state.status_code, 409)
        self.assertEqual(
            wrong_state.json(), {"error": "Solo se pueden reintentar tareas con error"}
        )
        self.assertEqual(hidden.status_code, 404)

    def test_reintentar_detecta_que_el_proyecto_fue_eliminado(self):
        original = db.create_task(
            self.user["id"], "Proyecto efímero", str(self.workspace)
        )
        db.update_task(original["id"], estado="error")
        self.workspace.rmdir()

        response = self.client.post(
            f"/api/tareas/{original['id']}/reintentar", headers=self.headers
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"error": "El proyecto original ya no está disponible"},
        )

    def test_reintentar_trata_workspace_historico_vacio_como_no_disponible(self):
        original = db.create_task(
            self.user["id"], "Tarea histórica", str(self.workspace)
        )
        db.update_task(original["id"], estado="error", workspace=None)

        response = self.client.post(
            f"/api/tareas/{original['id']}/reintentar", headers=self.headers
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"error": "El proyecto original ya no está disponible"},
        )

    def test_mensaje_rapido_conserva_contrato(self):
        with patch(
            "app.api.message_core.procesar_mensaje",
            AsyncMock(return_value=ResultadoMensaje("rapida", respuesta="hola")),
        ):
            response = self.client.post(
                "/api/mensaje", json={"texto": "hola"}, headers=self.headers
            )
        self.assertEqual(
            response.json(), {"via": "rapida", "respuesta": "hola"}
        )

    def test_mensaje_envia_el_modelo_claude_seleccionado_al_core(self):
        with patch(
            "app.api.message_core.procesar_mensaje",
            AsyncMock(return_value=ResultadoMensaje("rapida", respuesta="hola")),
        ) as procesar:
            response = self.client.post(
                "/api/mensaje",
                json={"texto": "hola", "modelo": "claude-opus-4-8"},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        procesar.assert_awaited_once_with(
            db.get_user_by_id(self.user["id"]),
            "hola",
            canal="pwa",
            modelo="claude-opus-4-8",
            client_ref=None,
            tool_ids=(),
        )

    def test_mensaje_rechaza_modelo_claude_desconocido(self):
        response = self.client.post(
            "/api/mensaje",
            json={"texto": "hola", "modelo": "claude-no-existe"},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"error": "Parámetros inválidos"})

    def test_mensaje_agentico_ambiguo_devuelve_409(self):
        result = ResultadoMensaje(
            "agentica",
            resolucion=ResolucionProyecto(
                "requiere_proyecto", proyectos=("alpha", "beta")
            ),
        )
        with patch(
            "app.api.message_core.procesar_mensaje", AsyncMock(return_value=result)
        ):
            response = self.client.post(
                "/api/mensaje", json={"texto": "haz el cambio"}, headers=self.headers
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("alpha, beta", response.json()["error"])

    def test_proyectos_y_clonado(self):
        with patch("app.api.tasks.listar_proyectos", return_value=["alpha"]), patch(
            "app.api.projects.clonar_proyecto",
            AsyncMock(return_value="nuevo"),
        ), patch("app.api.projects.eliminar_proyecto", return_value="alpha"):
            listed = self.client.get("/api/proyectos", headers=self.headers)
            cloned = self.client.post(
                "/api/proyectos/clonar",
                json={"url": "https://github.com/acme/nuevo.git"},
                headers=self.headers,
            )
            removed = self.client.delete(
                "/api/proyectos/alpha", headers=self.headers
            )
        self.assertEqual(listed.json(), {"proyectos": ["alpha"]})
        self.assertEqual(cloned.json(), {"proyecto": "nuevo"})
        self.assertEqual(removed.status_code, 204)

    def test_limite_invalido_respeta_formato_de_error(self):
        response = self.client.get("/api/tareas?limite=0", headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"error": "Parámetros inválidos"})

    def test_salud_sigue_publica_y_ruta_antigua_desaparece(self):
        self.assertEqual(self.client.get("/salud").status_code, 200)
        self.assertEqual(self.client.get("/tareas/cualquiera").status_code, 404)

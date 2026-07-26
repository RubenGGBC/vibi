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
                    "chat_provider": "groq",
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

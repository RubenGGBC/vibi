import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import auth, db
from app.config import settings
from app.main import create_app


class ApiEquipoTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.patches = [
            patch.object(settings, "db_path", str(root / "vibi.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
            patch.object(settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"),
        ]
        for parche in self.patches:
            parche.start()
            self.addCleanup(parche.stop)
        db.init_db()
        self.ana = db.get_or_create_user("ana")
        db.set_password_hash(self.ana["id"], auth.hash_password("correcta"))
        self.dani = db.get_or_create_user("dani")
        db.set_password_hash(self.dani["id"], auth.hash_password("correcta"))
        self.client = TestClient(create_app(False, root / "dist-ausente"))
        self.addCleanup(self.client.close)
        self.headers_ana = self._login("ana")
        self.headers_dani = self._login("dani")

    def _login(self, nombre):
        token = self.client.post(
            "/api/auth/login", json={"nombre": nombre, "contraseña": "correcta"}
        ).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_flujo_de_alta_miembro_y_tarea(self):
        creado = self.client.post(
            "/api/equipos", headers=self.headers_ana, json={"nombre": "Lanzamiento"}
        )
        self.assertEqual(creado.status_code, 200)
        equipo_id = creado.json()["equipo"]["id"]
        miembro = self.client.post(
            f"/api/equipos/{equipo_id}/miembros",
            headers=self.headers_ana,
            json={"nombre": "dani"},
        )
        self.assertEqual(miembro.status_code, 200)
        tarea = self.client.post(
            f"/api/equipos/{equipo_id}/tareas",
            headers=self.headers_ana,
            json={"titulo": "Entregar memoria", "asignada_a": self.dani["id"]},
        )
        self.assertEqual(tarea.status_code, 200)
        panel = self.client.get(f"/api/equipos/{equipo_id}", headers=self.headers_dani)
        self.assertEqual(panel.status_code, 200)
        self.assertEqual(panel.json()["tareas"][0]["titulo"], "Entregar memoria")

    def test_no_miembro_no_puede_leer_panel(self):
        creado = self.client.post(
            "/api/equipos", headers=self.headers_ana, json={"nombre": "Privado"}
        ).json()["equipo"]
        respuesta = self.client.get(
            f"/api/equipos/{creado['id']}", headers=self.headers_dani
        )
        self.assertEqual(respuesta.status_code, 404)

    def test_ruta_estatica_de_pendientes_no_se_confunde_con_equipo_id(self):
        respuesta = self.client.get(
            "/api/equipos/seguimientos/pendientes", headers=self.headers_ana
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {"seguimientos": []})

    def test_la_identidad_visual_se_puede_cambiar_despues_de_instalar(self):
        colores = {
            "color_cara": "#FFF9DD",
            "color_antifaz": "#2D2104",
            "color_sombrero": "#F5C518",
        }
        guardada = self.client.put(
            "/api/apariencia", headers=self.headers_ana, json=colores
        )
        self.assertEqual(guardada.status_code, 200)
        self.assertEqual(
            {clave: guardada.json()[clave] for clave in colores}, colores
        )
        leida = self.client.get("/api/apariencia", headers=self.headers_ana)
        self.assertEqual(
            {clave: leida.json()[clave] for clave in colores}, colores
        )

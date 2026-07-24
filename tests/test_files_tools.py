import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import auth, db, files, router, tools
from app.config import settings
from app.main import create_app


class FilesApiTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.patches = [
            patch.object(settings, "db_path", str(root / "morgana.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
            patch.object(settings, "file_storage_root", str(root / "files")),
            patch.object(settings, "file_max_bytes", 1024),
            patch.object(settings, "file_user_quota_bytes", 4096),
            patch.object(settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"),
        ]
        for setting_patch in self.patches:
            setting_patch.start()
            self.addCleanup(setting_patch.stop)

        db.init_db()
        self.user = db.get_or_create_user("ana")
        db.set_password_hash(self.user["id"], auth.hash_password("correcta"))
        self.other = db.get_or_create_user("pedro")
        db.set_password_hash(self.other["id"], auth.hash_password("correcta"))
        self.client = TestClient(create_app(start_background=False))
        self.addCleanup(self.client.close)
        self.headers = self._headers("ana")
        self.other_headers = self._headers("pedro")

    def _headers(self, name: str) -> dict[str, str]:
        token = self.client.post(
            "/api/auth/login",
            json={"nombre": name, "contraseña": "correcta"},
        ).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_busca_workspace_solo_del_usuario(self):
        own_root = Path(settings.workspace_root) / self.user["id"] / "documentos"
        own_root.mkdir(parents=True)
        (own_root / "matricula cuarto.pdf").write_bytes(b"contenido")
        other_root = Path(settings.workspace_root) / self.other["id"] / "documentos"
        other_root.mkdir(parents=True)
        (other_root / "matricula secreta.pdf").write_bytes(b"secreto")

        response = self.client.get(
            "/api/archivos?consulta=matricula&limite=20", headers=self.headers
        )

        self.assertEqual(response.status_code, 200)
        found = response.json()["archivos"]
        self.assertEqual([file["name"] for file in found], ["matricula cuarto.pdf"])
        self.assertNotIn(str(own_root), repr(found))
        self.assertNotIn("secreta", repr(found))

    def test_subida_se_descarga_en_otro_dispositivo_del_mismo_usuario(self):
        uploaded = self.client.post(
            "/api/archivos",
            headers=self.headers,
            files={"archivo": ("informe.txt", b"hola lab", "text/plain")},
        )
        self.assertEqual(uploaded.status_code, 201)
        file = uploaded.json()

        downloaded = self.client.get(file["download_url"], headers=self.headers)
        denied = self.client.get(file["download_url"], headers=self.other_headers)

        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, b"hola lab")
        self.assertIn("attachment", downloaded.headers["content-disposition"])
        self.assertEqual(denied.status_code, 404)

    def test_aplica_limite_y_cuota(self):
        response = self.client.post(
            "/api/archivos",
            headers=self.headers,
            files={"archivo": ("grande.bin", b"x" * 1025, "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 413)

    def test_catalogo_ejecuta_busqueda_y_crea_tool_personal(self):
        root = Path(settings.workspace_root) / self.user["id"]
        root.mkdir(parents=True)
        (root / "beca-2026.pdf").write_bytes(b"pdf")

        catalog = self.client.get("/api/herramientas", headers=self.headers)
        execution = self.client.post(
            "/api/herramientas/files.search/ejecutar",
            headers=self.headers,
            json={"arguments": {"query": "beca"}},
        )
        created = self.client.post(
            "/api/herramientas",
            headers=self.headers,
            json={
                "name": "Mis becas",
                "description": "Encuentra documentos de becas",
                "primitive_id": "files.search",
                "scope": "personal",
                "bound_arguments": {"query": "beca", "limit": 20},
            },
        )

        self.assertEqual(catalog.status_code, 200)
        self.assertIn("files.search", [tool["id"] for tool in catalog.json()["herramientas"]])
        self.assertEqual(execution.status_code, 200)
        self.assertEqual(execution.json()["result"]["files"][0]["name"], "beca-2026.pdf")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["scope"], "personal")
        other_catalog = self.client.get("/api/herramientas", headers=self.other_headers)
        self.assertNotIn(created.json()["id"], [tool["id"] for tool in other_catalog.json()["herramientas"]])

    def test_usuario_normal_no_publica_tool_del_lab(self):
        response = self.client.post(
            "/api/herramientas",
            headers=self.headers,
            json={
                "name": "Compartida",
                "description": "Tool compartida",
                "primitive_id": "system.health",
                "scope": "lab",
                "bound_arguments": {},
            },
        )
        self.assertEqual(response.status_code, 403)


class ToolRoutingTests(IsolatedAsyncioTestCase):
    async def test_reconoce_peticion_natural_de_archivo_sin_llamar_al_modelo(self):
        with patch("app.router.client") as client:
            result = await router.clasificar(
                "Pásame el archivo que tengo en el PC principal que se llama matrícula cuarto de carrera"
            )
        self.assertEqual(result["via"], "herramienta")
        self.assertEqual(result["herramienta"], "files.search")
        self.assertEqual(
            result["argumentos"]["query"], "matrícula cuarto de carrera"
        )
        client.assert_not_called()

    async def test_manifiestos_no_pueden_inventar_primitivas(self):
        user = {"id": "u1", "nombre": "Ana", "is_admin": 0}
        with self.assertRaises(tools.ToolNotFound):
            tools.create_custom_tool(
                user,
                "Shell",
                "Ejecuta comandos",
                "shell.run",
                "personal",
                {},
            )

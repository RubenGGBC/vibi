import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import auth, db, files, router, tasks, tools
from app.config import settings
from app.main import create_app


class ReviewedPresetArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    start: int
    end: int

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("code vacío")
        return normalized

    @model_validator(mode="after")
    def validate_range(self):
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("rango invertido")
        return self


class AliasedPresetArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(alias="external_code", min_length=2)


class FilesApiTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.patches = [
            patch.object(settings, "db_path", str(root / "vibi.db")),
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

    def test_navega_workspace_por_carpetas(self):
        root = Path(settings.workspace_root) / self.user["id"]
        documents = root / "documentos"
        empty = root / "vacía"
        documents.mkdir(parents=True)
        empty.mkdir()
        (root / "portada.txt").write_bytes(b"raiz")
        (documents / "matricula.pdf").write_bytes(b"pdf")

        top = self.client.get("/api/archivos?ruta=", headers=self.headers)
        nested = self.client.get(
            "/api/archivos?ruta=documentos", headers=self.headers
        )

        self.assertEqual(top.status_code, 200)
        self.assertEqual(
            [folder["name"] for folder in top.json()["carpetas"]],
            ["documentos", "vacía"],
        )
        self.assertEqual(
            [file["name"] for file in top.json()["archivos"]], ["portada.txt"]
        )
        self.assertEqual(nested.status_code, 200)
        self.assertEqual(nested.json()["ruta"], "documentos")
        self.assertEqual(
            [file["name"] for file in nested.json()["archivos"]],
            ["matricula.pdf"],
        )

    def test_no_permite_navegar_fuera_del_workspace(self):
        response = self.client.get(
            "/api/archivos?ruta=../otro", headers=self.headers
        )

        self.assertEqual(response.status_code, 400)

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

    def test_busca_nombre_opaco_por_el_contenido(self):
        uploaded = self.client.post(
            "/api/archivos",
            headers=self.headers,
            files={
                "archivo": (
                    "matr0010_712435_20260717.txt",
                    "Matrícula del cuarto curso del grado de Ingeniería Informática",
                    "text/plain",
                )
            },
        )
        self.assertEqual(uploaded.status_code, 201)

        response = self.client.get(
            "/api/archivos?consulta=matricula%20cuarto%20informatica",
            headers=self.headers,
        )
        read = self.client.post(
            "/api/herramientas/files.read/ejecutar",
            headers=self.headers,
            json={
                "arguments": {
                    "query": "mi matrícula de cuarto curso de informática"
                }
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["archivos"][0]["name"],
            "matr0010_712435_20260717.txt",
        )
        self.assertEqual(read.status_code, 200)
        self.assertIn("Ingeniería Informática", read.json()["result"]["content"])

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

    def test_primitivas_operativas_aislan_y_minimizan_datos(self):
        own_root = Path(settings.workspace_root) / self.user["id"]
        own_project = own_root / "atlas"
        own_project.mkdir(parents=True)
        other_project = Path(settings.workspace_root) / self.other["id"] / "secreto"
        other_project.mkdir(parents=True)
        own_task = db.create_task(
            self.user["id"], "prompt privado", str(own_project)
        )
        db.create_task(self.other["id"], "otro prompt", str(other_project))
        db.log_event("tarea_creada", self.user["id"], task_id=own_task["id"])

        projects = self.client.post(
            "/api/herramientas/projects.list/ejecutar",
            headers=self.headers,
            json={"arguments": {}},
        )
        listed_tasks = self.client.post(
            "/api/herramientas/tasks.list/ejecutar",
            headers=self.headers,
            json={"arguments": {"state": "pendiente", "limit": 10}},
        )
        recent = self.client.post(
            "/api/herramientas/activity.recent/ejecutar",
            headers=self.headers,
            json={"arguments": {"category": "tareas", "limit": 10}},
        )

        self.assertEqual(projects.status_code, 200)
        self.assertEqual(projects.json()["result"]["projects"], ["atlas"])
        self.assertEqual(listed_tasks.status_code, 200)
        task_result = listed_tasks.json()["result"]["tasks"]
        self.assertEqual([task["id"] for task in task_result], [own_task["id"]])
        self.assertEqual(task_result[0]["project"], "atlas")
        self.assertNotIn("prompt privado", repr(task_result))
        self.assertNotIn(str(own_root), repr(task_result))
        self.assertEqual(recent.status_code, 200)
        self.assertEqual(recent.json()["result"]["events"][0]["category"], "tareas")
        self.assertNotIn("payload", recent.json()["result"]["events"][0])

    def test_crea_nota_gestionada_y_respeta_aislamiento(self):
        response = self.client.post(
            "/api/herramientas/files.create_note/ejecutar",
            headers=self.headers,
            json={
                "arguments": {
                    "name": "resumen diario.md",
                    "content": "Pendientes revisados.",
                }
            },
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        file = result["file"]
        self.assertEqual(result["files"], [file])
        self.assertEqual(file["name"], "resumen diario.md")
        downloaded = self.client.get(file["download_url"], headers=self.headers)
        denied = self.client.get(file["download_url"], headers=self.other_headers)
        self.assertEqual(downloaded.content, "Pendientes revisados.".encode())
        self.assertEqual(denied.status_code, 404)

    def test_nota_aplica_el_limite_de_archivos(self):
        response = self.client.post(
            "/api/herramientas/files.create_note/ejecutar",
            headers=self.headers,
            json={"arguments": {"name": "enorme.txt", "content": "x" * 1025}},
        )

        history = self.client.get(
            "/api/herramientas/files.create_note/invocaciones",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["invocations"][0]["status"], "failed")
        self.assertEqual(
            history.json()["invocations"][0]["error_code"], "execution_failed"
        )

    def test_reserva_cuota_de_forma_atomica_ante_escrituras_concurrentes(self):
        barrier = threading.Barrier(2)

        def reserve(index: int):
            barrier.wait()
            return db.create_managed_file_within_quota(
                self.user["id"],
                f"nota-{index}.txt",
                f"storage-{index}",
                "text/plain",
                3_000,
                f"sha-{index}",
                4_096,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            stored = list(executor.map(reserve, range(2)))

        self.assertEqual(sum(file is not None for file in stored), 1)
        self.assertEqual(db.managed_usage(self.user["id"]), 3_000)

    def test_publica_blob_antes_de_confirmar_metadatos_y_limpia_si_fallan(self):
        observed_destination: list[bool] = []

        def fail_reservation(
            user_id: str,
            _name: str,
            storage_key: str,
            *_arguments,
        ):
            destination = (
                tasks.directorio_usuario(user_id)
                / files.MANAGED_UPLOADS_DIRECTORY
                / storage_key
            )
            observed_destination.append(destination.is_file())
            raise RuntimeError("fallo de SQLite")

        with patch(
            "app.files.db.create_managed_file_within_quota",
            side_effect=fail_reservation,
        ):
            with self.assertRaises(RuntimeError):
                files.create_text_file(self.user["id"], "nota.txt", "contenido")

        self.assertEqual(observed_destination, [True])
        user_root = (
            tasks.directorio_usuario(self.user["id"])
            / files.MANAGED_UPLOADS_DIRECTORY
        )
        self.assertEqual(list(user_root.iterdir()), [])

    def test_preset_parcial_deja_campos_para_la_ejecucion(self):
        created = self.client.post(
            "/api/herramientas",
            headers=self.headers,
            json={
                "name": "Guardar bitácora",
                "description": "Crea una nota con un nombre fijo",
                "primitive_id": "files.create_note",
                "scope": "personal",
                "bound_arguments": {"name": "bitacora.md"},
            },
        )

        self.assertEqual(created.status_code, 201)
        missing = self.client.post(
            f"/api/herramientas/{created.json()['id']}/ejecutar",
            headers=self.headers,
            json={"arguments": {}},
        )
        executed = self.client.post(
            f"/api/herramientas/{created.json()['id']}/ejecutar",
            headers=self.headers,
            json={"arguments": {"content": "Primera entrada"}},
        )
        invalid_preset = self.client.post(
            "/api/herramientas",
            headers=self.headers,
            json={
                "name": "Preset inválido",
                "description": "No acepta campos inventados",
                "primitive_id": "files.create_note",
                "scope": "personal",
                "bound_arguments": {"inventado": True},
            },
        )

        self.assertEqual(missing.status_code, 422)
        self.assertEqual(executed.status_code, 200)
        self.assertEqual(executed.json()["result"]["file"]["name"], "bitacora.md")
        self.assertEqual(invalid_preset.status_code, 422)

    def test_argumento_runtime_sustituye_el_preset(self):
        root = Path(settings.workspace_root) / self.user["id"]
        root.mkdir(parents=True)
        (root / "beca-2026.txt").write_text("beca")
        (root / "factura-2026.txt").write_text("factura")
        created = self.client.post(
            "/api/herramientas",
            headers=self.headers,
            json={
                "name": "Buscar becas",
                "description": "Búsqueda reemplazable",
                "primitive_id": "files.search",
                "scope": "personal",
                "bound_arguments": {"query": "beca"},
            },
        ).json()

        executed = self.client.post(
            f"/api/herramientas/{created['id']}/ejecutar",
            headers=self.headers,
            json={"arguments": {"query": "factura"}},
        )

        self.assertEqual(executed.status_code, 200)
        self.assertEqual(
            [file["name"] for file in executed.json()["result"]["files"]],
            ["factura-2026.txt"],
        )

    def test_edita_tool_propia_y_protege_propiedad_y_lab(self):
        created = self.client.post(
            "/api/herramientas",
            headers=self.headers,
            json={
                "name": "Buscar becas",
                "description": "Busca convocatorias",
                "primitive_id": "files.search",
                "scope": "personal",
                "bound_arguments": {"query": "becas"},
            },
        ).json()
        payload = {
            "name": "Buscar ayudas",
            "description": "Busca becas y ayudas",
            "primitive_id": "files.search",
            "scope": "personal",
            "bound_arguments": {"query": "ayudas", "limit": 12},
        }

        denied = self.client.put(
            f"/api/herramientas/{created['id']}",
            headers=self.other_headers,
            json=payload,
        )
        updated = self.client.put(
            f"/api/herramientas/{created['id']}",
            headers=self.headers,
            json=payload,
        )

        self.assertEqual(denied.status_code, 404)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Buscar ayudas")
        self.assertEqual(updated.json()["bound_arguments"]["limit"], 12)

        db.set_user_admin(self.user["id"], True)
        lab = self.client.post(
            "/api/herramientas",
            headers=self.headers,
            json={
                "name": "Salud del lab",
                "description": "Comprueba el servicio",
                "primitive_id": "system.health",
                "scope": "lab",
                "bound_arguments": {},
            },
        ).json()
        lab_denied = self.client.post(
            f"/api/herramientas/{lab['id']}/estado",
            headers=self.other_headers,
            json={"enabled": False},
        )
        lab_updated = self.client.put(
            f"/api/herramientas/{lab['id']}",
            headers=self.headers,
            json={**payload, "scope": "lab"},
        )

        self.assertEqual(lab_denied.status_code, 403)
        self.assertEqual(lab_updated.status_code, 200)
        self.assertEqual(lab_updated.json()["scope"], "lab")

        system_denied = self.client.put(
            "/api/herramientas/system.health",
            headers=self.headers,
            json=payload,
        )
        self.assertEqual(system_denied.status_code, 403)

    def test_duplica_tool_visible_como_personal(self):
        duplicated = self.client.post(
            "/api/herramientas/tasks.list/duplicar", headers=self.headers
        )

        self.assertEqual(duplicated.status_code, 201)
        self.assertEqual(duplicated.json()["scope"], "personal")
        self.assertEqual(duplicated.json()["primitive_id"], "tasks.list")
        self.assertEqual(duplicated.json()["name"], "Listar mis tareas (copia)")
        other_catalog = self.client.get(
            "/api/herramientas", headers=self.other_headers
        ).json()["herramientas"]
        self.assertNotIn(duplicated.json()["id"], [tool["id"] for tool in other_catalog])

    def test_historial_y_metricas_solo_incluyen_invocaciones_propias(self):
        succeeded = self.client.post(
            "/api/herramientas/system.health/ejecutar",
            headers=self.headers,
            json={"arguments": {}},
        )
        denied = self.client.post(
            "/api/herramientas/tasks.list/ejecutar",
            headers=self.headers,
            json={"arguments": {"state": "inventado"}},
        )
        self.client.post(
            "/api/herramientas/system.health/ejecutar",
            headers=self.other_headers,
            json={"arguments": {}},
        )

        history = self.client.get(
            "/api/herramientas/system.health/invocaciones?limite=10",
            headers=self.headers,
        )
        catalog = self.client.get(
            "/api/herramientas", headers=self.headers
        ).json()["herramientas"]
        health = next(tool for tool in catalog if tool["id"] == "system.health")
        task_list = next(tool for tool in catalog if tool["id"] == "tasks.list")

        self.assertEqual(succeeded.status_code, 200)
        self.assertEqual(denied.status_code, 422)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()["invocations"]), 1)
        self.assertEqual(history.json()["invocations"][0]["status"], "succeeded")
        self.assertEqual(health["usage"]["total"], 1)
        self.assertEqual(health["usage"]["succeeded"], 1)
        self.assertEqual(task_list["usage"]["denied"], 1)
        self.assertEqual(task_list["usage"]["success_rate"], 0)


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

    async def test_detecta_peticion_contextual_para_leer_archivo(self):
        with patch("app.router.client") as client:
            result = await router.clasificar(
                "Vibi, tengo subida una matrícula de cuarto curso de informática, ¿puedes leerme el contenido?"
            )

        self.assertEqual(result["via"], "herramienta")
        self.assertEqual(result["herramienta"], "files.read")
        self.assertIn("matrícula", result["argumentos"]["query"])
        client.assert_not_called()

    async def test_reutiliza_ultimo_archivo_en_una_pregunta_de_seguimiento(self):
        history = [
            {
                "role": "assistant",
                "content": "He encontrado 1 archivo(s): matr0010_712435.pdf.",
            }
        ]
        with patch("app.router.client") as client:
            result = await router.clasificar(
                "Dime qué pone dentro, porfa", history
            )

        self.assertEqual(result["herramienta"], "files.read")
        self.assertEqual(result["argumentos"]["query"], "matr0010_712435.pdf")
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

    async def test_usuario_configurado_orquesta_con_el_perfil_tools(self):
        classification = (
            '{"via":"herramienta","proyecto":null,'
            '"herramienta":"files.search",'
            '"argumentos":{"query":"matrícula"}}'
        )
        with patch(
            "app.router.ai_providers.complete_text",
            AsyncMock(return_value=classification),
        ) as complete:
            result = await router.clasificar(
                "Busca mi archivo de matrícula", user_id="u1"
            )

        self.assertEqual(result["herramienta"], "files.search")
        complete.assert_awaited_once()
        self.assertEqual(complete.await_args.args[1], "tools")


class ToolPresetValidationTests(TestCase):
    def setUp(self):
        self.primitive = tools.Primitive(
            "reviewed.preset",
            "Preset revisado",
            "Ejercita validadores Pydantic",
            (),
            (),
            ReviewedPresetArguments,
            AsyncMock(),
        )

    def test_preserva_transformaciones_de_field_validator(self):
        validated = tools.validate_bound_arguments(
            self.primitive, {"code": "  abc  "}
        )

        self.assertEqual(validated, {"code": "ABC"})

    def test_ejecuta_model_validator_sobre_campos_presentes(self):
        with self.assertRaises(tools.InvalidToolArguments):
            tools.validate_bound_arguments(
                self.primitive, {"start": 10, "end": 2}
            )

    def test_conserva_alias_y_restricciones_de_field_info(self):
        primitive = tools.Primitive(
            "aliased.preset",
            "Preset con alias",
            "Publica un nombre externo",
            (),
            (),
            AliasedPresetArguments,
            AsyncMock(),
        )

        validated = tools.validate_bound_arguments(
            primitive, {"external_code": "AB"}
        )

        self.assertEqual(validated, {"external_code": "AB"})

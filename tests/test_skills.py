import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import auth, db, skills, tools
from app.config import settings
from app.core import messages
from app.main import create_app


class SkillDomainTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.db_patch = patch.object(settings, "db_path", str(root / "morgana.db"))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        db.init_db()
        self.user = db.get_or_create_user("ana")
        self.other = db.get_or_create_user("pedro")

    def valid_payload(self, **overrides) -> dict:
        payload = {
            "name": "Resumir expediente",
            "slug": "resumir-expediente",
            "description": "Resume documentos administrativos con una estructura estable.",
            "instructions": (
                "Extrae los datos principales, señala ausencias y termina con "
                "los siguientes pasos recomendados."
            ),
            "examples": ["Resume mi matrícula de cuarto curso"],
            "tool_ids": ["files.read"],
            "scope": "personal",
        }
        payload.update(overrides)
        return payload

    def test_editing_creates_an_immutable_version(self):
        created = skills.create_skill(self.user, self.valid_payload())

        updated = skills.update_skill(
            self.user,
            created["id"],
            self.valid_payload(name="Expediente breve"),
        )
        versions = skills.list_versions(self.user, created["id"])

        self.assertEqual(updated["version"], 2)
        self.assertEqual([item["version"] for item in versions], [2, 1])
        self.assertEqual(versions[0]["snapshot"]["name"], "Expediente breve")
        self.assertEqual(versions[1]["snapshot"]["name"], "Resumir expediente")

    def test_personal_skill_is_invisible_to_other_users(self):
        created = skills.create_skill(self.user, self.valid_payload())

        visible_ids = {skill["id"] for skill in skills.list_visible(self.other)}

        self.assertNotIn(created["id"], visible_ids)
        with self.assertRaises(skills.SkillNotFound):
            skills.list_versions(self.other, created["id"])

    def test_incomplete_draft_cannot_be_activated(self):
        draft = skills.create_skill(
            self.user,
            self.valid_payload(
                description="Breve",
                instructions="Resume.",
                examples=[],
                tool_ids=[],
            ),
        )

        self.assertFalse(draft["quality"]["ready"])
        with self.assertRaises(skills.InvalidSkill):
            skills.set_enabled(self.user, draft["id"], True)

    def test_editing_an_active_skill_into_an_invalid_state_returns_it_to_draft(self):
        created = skills.create_skill(self.user, self.valid_payload())
        skills.set_enabled(self.user, created["id"], True)

        updated = skills.update_skill(
            self.user,
            created["id"],
            self.valid_payload(instructions="Demasiado breve"),
        )

        self.assertFalse(updated["enabled"])
        self.assertFalse(updated["quality"]["ready"])
        self.assertEqual(updated["version"], 2)

    def test_duplicate_has_independent_slug_history_and_state(self):
        created = skills.create_skill(self.user, self.valid_payload())
        active = skills.set_enabled(self.user, created["id"], True)

        duplicate = skills.duplicate_skill(self.user, active["id"])

        self.assertTrue(active["enabled"])
        self.assertFalse(duplicate["enabled"])
        self.assertEqual(duplicate["slug"], "resumir-expediente-copia")
        self.assertEqual(duplicate["version"], 1)
        self.assertEqual(
            [item["version"] for item in skills.list_versions(self.user, duplicate["id"])],
            [1],
        )

    def test_export_compiles_a_portable_skill_markdown(self):
        created = skills.create_skill(self.user, self.valid_payload())

        exported = skills.export_skill(self.user, created["id"])

        self.assertEqual(exported["filename"], "resumir-expediente.SKILL.md")
        self.assertIn("---\nname: resumir-expediente", exported["content"])
        self.assertIn("## Instrucciones", exported["content"])
        self.assertIn("`files.read`", exported["content"])
        self.assertIn("/skill resumir-expediente", exported["content"])

    def test_explicit_command_resolves_only_an_active_skill(self):
        created = skills.create_skill(self.user, self.valid_payload())

        self.assertEqual(
            skills.parse_command(
                "/skill resumir-expediente Resume mi matrícula de cuarto"
            ),
            ("resumir-expediente", "Resume mi matrícula de cuarto"),
        )
        self.assertIsNone(
            skills.get_active_by_slug(self.user, "resumir-expediente")
        )

        skills.set_enabled(self.user, created["id"], True)

        self.assertEqual(
            skills.get_active_by_slug(self.user, "resumir-expediente")["id"],
            created["id"],
        )

    def test_disabling_a_dependency_pauses_the_active_skill(self):
        custom_tool = tools.create_custom_tool(
            self.user,
            "Comprobar servicio",
            "Comprueba el estado antes de elaborar la respuesta",
            "system.health",
            "personal",
            {},
        )
        created = skills.create_skill(
            self.user,
            self.valid_payload(
                slug="comprobar-expediente", tool_ids=[custom_tool["id"]]
            ),
        )
        skills.set_enabled(self.user, created["id"], True)

        db.set_tool_enabled(custom_tool["id"], self.user["id"], False)
        visible = skills.list_visible(self.user)[0]

        self.assertFalse(visible["enabled"])
        self.assertFalse(visible["quality"]["ready"])
        self.assertIsNone(
            skills.get_active_by_slug(self.user, "comprobar-expediente")
        )


class SkillRunnerTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.patches = [
            patch.object(settings, "db_path", str(root / "morgana.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
        ]
        for setting_patch in self.patches:
            setting_patch.start()
            self.addCleanup(setting_patch.stop)
        db.init_db()
        self.user = db.get_or_create_user("ana")
        workspace = Path(settings.workspace_root) / self.user["id"]
        workspace.mkdir(parents=True)
        (workspace / "beca-2026.txt").write_text("Concedida por 2.000 euros", encoding="utf-8")

    async def test_runner_executes_only_declared_real_tools(self):
        created = skills.create_skill(
            self.user,
            {
                "name": "Localizar beca",
                "slug": "localizar-beca",
                "description": "Localiza y explica documentos personales relacionados con becas.",
                "instructions": (
                    "Indica el archivo encontrado y resume el dato económico "
                    "principal con una frase clara."
                ),
                "examples": ["Busca la resolución de mi beca"],
                "tool_ids": ["files.search"],
                "scope": "personal",
            },
        )
        active = skills.set_enabled(self.user, created["id"], True)
        complete = AsyncMock(
            side_effect=[
                '{"query":"beca","limit":20}',
                "He encontrado beca-2026.txt, con una ayuda de dos mil euros.",
            ]
        )

        with patch("app.skills.ai_providers.complete_text", complete):
            result = await skills.run_skill(
                self.user, active["id"], "Busca la resolución de mi beca"
            )

        self.assertEqual(
            result["response"],
            "He encontrado beca-2026.txt, con una ayuda de dos mil euros.",
        )
        self.assertEqual(result["tool_runs"][0]["tool_id"], "files.search")
        self.assertEqual(result["artifacts"][0]["name"], "beca-2026.txt")
        self.assertEqual(len(complete.await_args_list), 2)

    async def test_chat_command_persists_the_skill_turn_without_using_router(self):
        created = skills.create_skill(
            self.user,
            {
                "name": "Localizar beca",
                "slug": "localizar-beca",
                "description": "Localiza y explica documentos personales relacionados con becas.",
                "instructions": (
                    "Indica el archivo encontrado y resume el dato económico "
                    "principal con una frase clara."
                ),
                "examples": ["Busca la resolución de mi beca"],
                "tool_ids": [],
                "scope": "personal",
            },
        )
        skills.set_enabled(self.user, created["id"], True)
        run_result = {
            "response": "La ayuda concedida es de dos mil euros.",
            "artifacts": [],
        }

        with patch(
            "app.core.messages.skills.run_skill",
            AsyncMock(return_value=run_result),
        ), patch(
            "app.core.messages.router.clasificar",
            AsyncMock(side_effect=AssertionError("el comando no debe clasificarse")),
        ):
            result = await messages.procesar_mensaje(
                self.user,
                "/skill localizar-beca Busca mi resolución",
                canal="pwa",
                client_ref="skill-1",
            )

        conversation = db.get_active_conversation(self.user["id"])
        self.assertIsNotNone(conversation)
        stored = db.list_active_conversation_messages(self.user["id"], 10)
        self.assertEqual(result.via, "herramienta")
        self.assertEqual(result.respuesta, "La ayuda concedida es de dos mil euros.")
        self.assertEqual(
            [message["content"] for message in stored],
            [
                "/skill localizar-beca Busca mi resolución",
                "La ayuda concedida es de dos mil euros.",
            ],
        )


class SkillApiTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.patches = [
            patch.object(settings, "db_path", str(root / "morgana.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
            patch.object(
                settings,
                "jwt_secret",
                "secreto-de-pruebas-para-skills-con-mas-de-32-bytes",
            ),
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
        response = self.client.post(
            "/api/auth/login",
            json={"nombre": name, "contraseña": "correcta"},
        )
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def payload(self, **overrides) -> dict:
        payload = {
            "name": "Preparar informe",
            "slug": "preparar-informe",
            "description": "Convierte una petición en un informe breve y accionable.",
            "instructions": (
                "Redacta un resumen ejecutivo, separa los riesgos y termina "
                "con tres acciones concretas."
            ),
            "examples": ["Prepara el informe semanal del laboratorio"],
            "tool_ids": [],
            "scope": "personal",
        }
        payload.update(overrides)
        return payload

    def test_full_skill_lifecycle_is_exposed_by_the_api(self):
        created_response = self.client.post(
            "/api/skills", headers=self.headers, json=self.payload()
        )
        self.assertEqual(created_response.status_code, 201)
        created = created_response.json()

        catalog = self.client.get("/api/skills", headers=self.headers).json()
        self.assertEqual(catalog["summary"], {"active": 0, "drafts": 1})
        self.assertEqual(catalog["skills"][0]["id"], created["id"])
        self.assertIn("files.read", {tool["id"] for tool in catalog["available_tools"]})

        updated_response = self.client.put(
            f"/api/skills/{created['id']}",
            headers=self.headers,
            json=self.payload(name="Informe de guardia"),
        )
        self.assertEqual(updated_response.status_code, 200)
        self.assertEqual(updated_response.json()["version"], 2)

        versions = self.client.get(
            f"/api/skills/{created['id']}/versiones", headers=self.headers
        )
        self.assertEqual([item["version"] for item in versions.json()], [2, 1])

        activated = self.client.post(
            f"/api/skills/{created['id']}/estado",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(activated.status_code, 200)
        self.assertTrue(activated.json()["enabled"])

        duplicate = self.client.post(
            f"/api/skills/{created['id']}/duplicar", headers=self.headers
        )
        self.assertEqual(duplicate.status_code, 201)
        self.assertFalse(duplicate.json()["enabled"])

        exported = self.client.get(
            f"/api/skills/{created['id']}/exportar", headers=self.headers
        )
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()["filename"], "preparar-informe.SKILL.md")

    def test_playground_runs_a_draft_owned_by_the_user(self):
        created = self.client.post(
            "/api/skills", headers=self.headers, json=self.payload()
        ).json()
        with patch(
            "app.skills.ai_providers.complete_text",
            AsyncMock(return_value="Informe preparado."),
        ):
            response = self.client.post(
                f"/api/skills/{created['id']}/probar",
                headers=self.headers,
                json={"input": "Resume la semana"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response"], "Informe preparado.")
        self.assertEqual(response.json()["tool_runs"], [])

    def test_api_enforces_ownership_quality_and_lab_permissions(self):
        created = self.client.post(
            "/api/skills",
            headers=self.headers,
            json=self.payload(
                description="Breve", instructions="Hazlo.", examples=[]
            ),
        ).json()

        hidden = self.client.get(
            f"/api/skills/{created['id']}/versiones", headers=self.other_headers
        )
        not_ready = self.client.post(
            f"/api/skills/{created['id']}/estado",
            headers=self.headers,
            json={"enabled": True},
        )
        forbidden_lab = self.client.post(
            "/api/skills",
            headers=self.headers,
            json=self.payload(slug="skill-lab", scope="lab"),
        )
        too_many_tools = self.client.post(
            "/api/skills",
            headers=self.headers,
            json=self.payload(tool_ids=["a", "b", "c", "d", "e"]),
        )

        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(not_ready.status_code, 409)
        self.assertEqual(forbidden_lab.status_code, 403)
        self.assertEqual(too_many_tools.status_code, 422)

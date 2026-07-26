import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from app import projects
from app.config import settings


class RepoUrlTests(TestCase):
    def test_acepta_github_https(self):
        self.assertEqual(
            projects.validar_url_repo("https://github.com/openai/codex.git"),
            ("github.com", "codex"),
        )

    def test_acepta_ssh_de_hosts_conocidos(self):
        self.assertEqual(
            projects.validar_url_repo("git@gitlab.com:equipo/proyecto.git"),
            ("gitlab.com", "proyecto"),
        )

    def test_rechaza_https_fuera_de_github(self):
        with self.assertRaises(projects.InvalidRepoUrl):
            projects.validar_url_repo("https://example.com/equipo/proyecto.git")

    def test_rechaza_url_con_opciones_o_traversal(self):
        for url in (
            "--upload-pack=malicioso",
            "file:///tmp/repo",
            "https://github.com/../.git",
            "https://user@github.com/equipo/repo.git",
        ):
            with self.subTest(url=url), self.assertRaises(projects.InvalidRepoUrl):
                projects.validar_url_repo(url)


class CloneProjectTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.settings_patch = patch.object(settings, "workspace_root", str(self.root))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    async def test_clona_con_argv_y_mueve_al_destino_saneado(self):
        process = AsyncMock()
        process.returncode = 0
        process.communicate.return_value = (b"", b"")

        async def fake_subprocess(*args, **kwargs):
            Path(args[-1]).mkdir()
            return process

        with patch(
            "app.projects.asyncio.create_subprocess_exec",
            side_effect=fake_subprocess,
        ) as create_process:
            name = await projects.clonar_proyecto(
                "u1", "https://github.com/openai/codex.git"
            )

        self.assertEqual(name, "codex")
        self.assertTrue((self.root / "u1" / "codex").is_dir())
        args = create_process.call_args.args
        self.assertEqual(args[:3], ("git", "clone", "--"))
        self.assertEqual(args[3], "https://github.com/openai/codex.git")

    async def test_no_sobrescribe_proyecto_existente(self):
        (self.root / "u1" / "codex").mkdir(parents=True)
        with self.assertRaises(projects.ProjectExists):
            await projects.clonar_proyecto(
                "u1", "https://github.com/openai/codex.git"
            )

    async def test_fallo_de_git_limpia_directorio_temporal(self):
        process = AsyncMock()
        process.returncode = 128
        process.communicate.return_value = (b"", b"repositorio privado")

        async def fake_subprocess(*args, **kwargs):
            Path(args[-1]).mkdir()
            return process

        with patch(
            "app.projects.asyncio.create_subprocess_exec",
            side_effect=fake_subprocess,
        ):
            with self.assertRaisesRegex(projects.CloneFailed, "repositorio privado"):
                await projects.clonar_proyecto(
                    "u1", "https://github.com/openai/codex.git"
                )

        self.assertEqual(list((self.root / "u1").iterdir()), [])

    async def test_user_id_no_puede_escapar_del_workspace(self):
        with self.assertRaises(ValueError):
            await projects.clonar_proyecto(
                "../fuera", "https://github.com/openai/codex.git"
            )


class DeleteProjectTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.settings_patch = patch.object(settings, "workspace_root", str(self.root))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_elimina_directorio_y_contenido(self):
        project = self.root / "u1" / "demo"
        project.mkdir(parents=True)
        (project / "README.md").write_text("demo", encoding="utf-8")

        with patch("app.projects.db.list_live_tasks", return_value=[]):
            removed = projects.eliminar_proyecto("u1", "demo")

        self.assertEqual(removed, "demo")
        self.assertFalse(project.exists())

    def test_bloquea_proyecto_con_tarea_activa(self):
        project = self.root / "u1" / "demo"
        project.mkdir(parents=True)
        active = [{"workspace": str(project), "estado": "ejecutando"}]

        with patch("app.projects.db.list_live_tasks", return_value=active):
            with self.assertRaises(projects.ProjectInUse):
                projects.eliminar_proyecto("u1", "demo")

        self.assertTrue(project.exists())

    def test_no_elimina_rutas_fuera_del_usuario(self):
        outside = self.root / "fuera"
        outside.mkdir()

        with self.assertRaises(projects.ProjectNotFound):
            projects.eliminar_proyecto("u1", "../fuera")

        self.assertTrue(outside.exists())

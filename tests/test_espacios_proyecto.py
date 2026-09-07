"""Proyectos como espacio: archivos subidos, conversaciones guardadas y adjuntos.

Lo que se prueba aquí no es que las rutas contesten 200, sino las tres promesas
que hace la función: que lo que se sube a un proyecto se encuentra dentro de él,
que una conversación guardada se puede retomar tal cual se dejó, y que un
archivo adjuntado a un mensaje llega al motor con su contenido y no solo con su
nombre.
"""
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app import auth, db, files, projects
from app.config import settings
from app.executors.chat_engine import ChatResult
from app.main import create_app


class EntornoDeUsuario:
    """Un usuario con su workspace y su base, aisladas de las de verdad."""

    def montar(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.root = root
        for setting_patch in (
            patch.object(settings, "db_path", str(root / "vibi.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
            patch.object(
                settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"
            ),
        ):
            setting_patch.start()
            self.addCleanup(setting_patch.stop)
        db.init_db()
        self.user = db.get_or_create_user("ruben")
        db.set_password_hash(self.user["id"], auth.hash_password("correcta"))


class ProyectosComoEspacio(EntornoDeUsuario, TestCase):
    def setUp(self):
        self.montar()
        self.client = TestClient(
            create_app(start_background=False, frontend_dir=self.root / "sin-dist")
        )
        self.addCleanup(self.client.close)
        token = self.client.post(
            "/api/auth/login",
            json={"nombre": "ruben", "contraseña": "correcta"},
        ).json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    def _crear(self, nombre: str = "Mi Tesis", descripcion: str = "") -> dict:
        response = self.client.post(
            "/api/proyectos",
            json={"nombre": nombre, "descripcion": descripcion},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_crear_proyecto_deja_carpeta_y_ficha(self):
        proyecto = self._crear("Mi Tesis", "todo lo del TFG")
        self.assertEqual(proyecto["slug"], "Mi-Tesis")
        self.assertEqual(proyecto["descripcion"], "todo lo del TFG")
        carpeta = self.root / "workspace" / self.user["id"] / "Mi-Tesis"
        self.assertTrue(carpeta.is_dir())

        listado = self.client.get("/api/proyectos", headers=self.headers).json()
        self.assertIn("Mi-Tesis", listado["proyectos"])
        self.assertEqual([d["nombre"] for d in listado["detalles"]], ["Mi Tesis"])

    def test_nombre_repetido_no_crea_un_segundo_proyecto(self):
        self._crear("Tesis")
        repetido = self.client.post(
            "/api/proyectos", json={"nombre": "Tesis"}, headers=self.headers
        )
        self.assertEqual(repetido.status_code, 409)
        self.assertEqual(len(db.list_projects(self.user["id"])), 1)

    def test_nombre_sin_letras_ni_numeros_se_rechaza(self):
        response = self.client.post(
            "/api/proyectos", json={"nombre": "///"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_una_carpeta_clonada_a_mano_aparece_como_proyecto(self):
        (self.root / "workspace" / self.user["id"] / "repo-viejo").mkdir(parents=True)
        listado = self.client.get("/api/proyectos", headers=self.headers).json()
        self.assertEqual([d["slug"] for d in listado["detalles"]], ["repo-viejo"])

    def test_lo_subido_al_proyecto_se_encuentra_dentro_de_el(self):
        proyecto = self._crear("Tesis")
        subida = self.client.post(
            f"/api/proyectos/{proyecto['id']}/archivos",
            files={"archivo": ("notas.txt", b"capitulo uno", "text/plain")},
            headers=self.headers,
        )
        self.assertEqual(subida.status_code, 201, subida.text)
        self.assertEqual(subida.json()["project_id"], proyecto["id"])

        dentro = self.client.get(
            f"/api/proyectos/{proyecto['id']}/archivos", headers=self.headers
        ).json()
        self.assertEqual([a["name"] for a in dentro["archivos"]], ["notas.txt"])
        self.assertEqual(dentro["proyecto"]["archivos"], 1)

    def test_sacar_un_archivo_del_proyecto_no_lo_borra(self):
        proyecto = self._crear("Tesis")
        archivo = self.client.post(
            f"/api/proyectos/{proyecto['id']}/archivos",
            files={"archivo": ("notas.txt", b"capitulo uno", "text/plain")},
            headers=self.headers,
        ).json()

        fuera = self.client.delete(
            f"/api/proyectos/{proyecto['id']}/archivos/{archivo['id']}",
            headers=self.headers,
        )
        self.assertEqual(fuera.status_code, 204)
        self.assertIsNone(
            db.get_file_for_user(archivo["id"], self.user["id"])["project_id"]
        )
        descarga = self.client.get(
            f"/api/archivos/{archivo['id']}/contenido", headers=self.headers
        )
        self.assertEqual(descarga.content, b"capitulo uno")

    def test_un_archivo_ya_subido_se_puede_meter_en_el_proyecto(self):
        proyecto = self._crear("Tesis")
        suelto = self.client.post(
            "/api/archivos",
            files={"archivo": ("suelto.txt", b"algo", "text/plain")},
            headers=self.headers,
        ).json()
        movido = self.client.put(
            f"/api/proyectos/{proyecto['id']}/archivos/{suelto['id']}",
            headers=self.headers,
        )
        self.assertEqual(movido.status_code, 200, movido.text)
        self.assertEqual(movido.json()["project_id"], proyecto["id"])

    def test_guardar_la_conversacion_la_deja_en_el_proyecto_sin_cerrarla(self):
        proyecto = self._crear("Tesis")
        conversacion = db.get_or_create_active_conversation(self.user["id"])
        db.add_conversation_message(
            conversacion["id"], "user", "¿Cómo estructuro el capítulo 3?", "pwa"
        )

        guardada = self.client.post(
            "/api/conversations/active/guardar",
            json={"project_id": proyecto["id"]},
            headers=self.headers,
        )
        self.assertEqual(guardada.status_code, 200, guardada.text)
        # Sin título, el primer mensaje sirve de nombre.
        self.assertEqual(
            guardada.json()["titulo"], "¿Cómo estructuro el capítulo 3?"
        )
        # Guardar no cierra: se sigue hablando en la misma.
        self.assertEqual(guardada.json()["estado"], "activa")
        self.assertEqual(
            db.get_active_conversation(self.user["id"])["id"], conversacion["id"]
        )

        dentro = self.client.get(
            f"/api/proyectos/{proyecto['id']}/conversaciones", headers=self.headers
        ).json()
        self.assertEqual(
            [c["id"] for c in dentro["conversaciones"]], [conversacion["id"]]
        )
        self.assertEqual(dentro["conversaciones"][0]["mensajes"], 1)

    def test_una_conversacion_guardada_se_retoma_donde_se_dejo(self):
        proyecto = self._crear("Tesis")
        primera = db.get_or_create_active_conversation(self.user["id"])
        db.add_conversation_message(primera["id"], "user", "lo de antes", "pwa")
        self.client.post(
            "/api/conversations/active/guardar",
            json={"project_id": proyecto["id"], "titulo": "Charla vieja"},
            headers=self.headers,
        )
        with patch("app.api.chat.close_session", AsyncMock()):
            self.client.post("/api/conversations/reset", headers=self.headers)
            segunda = db.get_active_conversation(self.user["id"])
            self.assertNotEqual(segunda["id"], primera["id"])

            reanudada = self.client.post(
                f"/api/conversaciones/{primera['id']}/reanudar", headers=self.headers
            )
        self.assertEqual(reanudada.status_code, 200, reanudada.text)
        self.assertEqual(reanudada.json()["conversation_id"], primera["id"])
        self.assertEqual(
            [m["content"] for m in reanudada.json()["messages"]], ["lo de antes"]
        )
        self.assertEqual(
            db.get_active_conversation(self.user["id"])["id"], primera["id"]
        )

    def test_la_conversacion_de_otro_usuario_no_se_puede_retomar(self):
        otra = db.get_or_create_user("ajena")
        suya = db.get_or_create_active_conversation(otra["id"])
        response = self.client.post(
            f"/api/conversaciones/{suya['id']}/reanudar", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

    def test_borrar_el_proyecto_no_se_lleva_lo_que_habia_dentro(self):
        proyecto = self._crear("Tesis")
        archivo = self.client.post(
            f"/api/proyectos/{proyecto['id']}/archivos",
            files={"archivo": ("notas.txt", b"capitulo uno", "text/plain")},
            headers=self.headers,
        ).json()
        conversacion = db.get_or_create_active_conversation(self.user["id"])
        self.client.post(
            "/api/conversations/active/guardar",
            json={"project_id": proyecto["id"], "titulo": "Charla"},
            headers=self.headers,
        )

        borrado = self.client.delete(
            f"/api/proyectos/{proyecto['id']}", headers=self.headers
        )
        self.assertEqual(borrado.status_code, 204)
        self.assertIsNone(db.get_project(proyecto["id"], self.user["id"]))
        self.assertFalse(
            (self.root / "workspace" / self.user["id"] / "Tesis").exists()
        )
        # El archivo y la conversación siguen siendo del usuario, solo que sueltos.
        vivo = db.get_file_for_user(archivo["id"], self.user["id"])
        self.assertIsNone(vivo["project_id"])
        self.assertIsNone(vivo["deleted_at"])
        self.assertIsNone(
            db.get_conversation(conversacion["id"], self.user["id"])["project_id"]
        )


class AdjuntarArchivosAUnTurno(EntornoDeUsuario, IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.montar()
        self.subido = await files.store_stream(
            self.user["id"],
            "receta.txt",
            self._trozos(b"Sofreir la cebolla a fuego lento."),
            content_type="text/plain",
        )

    @staticmethod
    async def _trozos(contenido: bytes):
        yield contenido

    async def test_el_motor_recibe_el_contenido_del_adjunto(self):
        from app.executors import chat

        motor = AsyncMock()
        motor.name = "anthropic"
        motor.display_name = "Claude"
        # `needs_history` es síncrono: con el AsyncMock de serie devolvía una
        # corrutina que nadie espera, y el turno creía que sí hacía falta.
        motor.needs_history = MagicMock(return_value=False)
        motor.conversation_lock = lambda _: asyncio.Lock()
        motor.run_turn.return_value = ChatResult(response="Va con cebolla.")

        with patch("app.executors.chat.engine_for", return_value=motor), patch(
            "app.executors.chat.events.mensaje_chat", AsyncMock()
        ), patch("app.executors.chat.events.inicio_respuesta_chat", AsyncMock()), patch(
            "app.executors.chat.events.fin_respuesta_chat", AsyncMock()
        ), patch("app.executors.chat.db.log_event"):
            resultado = await chat.respond(
                self.user,
                "¿Qué lleva?",
                "pwa",
                attached_file_ids=(self.subido["id"],),
            )

        self.assertEqual(resultado.response, "Va con cebolla.")
        texto = motor.run_turn.await_args.args[2]
        self.assertIn("¿Qué lleva?", texto)
        self.assertIn("receta.txt", texto)
        # El contenido va dentro del turno: el modelo no tiene que ir a buscarlo.
        self.assertIn("Sofreir la cebolla a fuego lento.", texto)

    async def test_el_adjunto_queda_unido_al_mensaje_y_no_a_su_texto(self):
        from app.executors import chat

        motor = AsyncMock()
        motor.name = "anthropic"
        motor.display_name = "Claude"
        # `needs_history` es síncrono: con el AsyncMock de serie devolvía una
        # corrutina que nadie espera, y el turno creía que sí hacía falta.
        motor.needs_history = MagicMock(return_value=False)
        motor.conversation_lock = lambda _: asyncio.Lock()
        motor.run_turn.return_value = ChatResult(response="Listo.")

        with patch("app.executors.chat.engine_for", return_value=motor), patch(
            "app.executors.chat.events.mensaje_chat", AsyncMock()
        ), patch("app.executors.chat.events.inicio_respuesta_chat", AsyncMock()), patch(
            "app.executors.chat.events.fin_respuesta_chat", AsyncMock()
        ), patch("app.executors.chat.db.log_event"):
            await chat.respond(
                self.user,
                "¿Qué lleva?",
                "pwa",
                attached_file_ids=(self.subido["id"],),
            )

        conversacion = db.get_active_conversation(self.user["id"])
        mensajes = db.list_conversation_messages(conversacion["id"], self.user["id"])
        del_usuario = [m for m in mensajes if m["role"] == "user"][0]
        # Lo guardado es lo que la persona escribió, sin el volcado del archivo.
        self.assertEqual(del_usuario["content"], "¿Qué lleva?")
        adjuntos = db.attachments_for_messages([del_usuario["id"]])
        self.assertEqual(
            [a["name"] for a in adjuntos[del_usuario["id"]]], ["receta.txt"]
        )

    async def test_un_adjunto_ajeno_se_ignora_en_vez_de_filtrarse(self):
        otra = db.get_or_create_user("ajena")
        suyo = await files.store_stream(
            otra["id"], "privado.txt", self._trozos(b"secreto"), content_type="text/plain"
        )
        resueltos = files.resolver_adjuntos(self.user["id"], (suyo["id"],))
        self.assertEqual(resueltos, [])


class NombreDeCarpetaDelProyecto(TestCase):
    def test_convierte_el_nombre_visible_en_carpeta_segura(self):
        self.assertEqual(projects.slug_de("Trabajo Fin de Grado"), "Trabajo-Fin-de-Grado")
        self.assertEqual(projects.slug_de("  Cañón/2026  "), "Canon-2026")

    def test_rechaza_lo_que_no_deja_carpeta_utilizable(self):
        for nombre in ("", "   ", "..", "///", "."):
            with self.subTest(nombre=nombre):
                with self.assertRaises(projects.InvalidProjectName):
                    projects.slug_de(nombre)

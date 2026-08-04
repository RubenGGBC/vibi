import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app import db
from app.config import settings


class ActivityDataTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_patch = patch.object(
            settings, "db_path", str(Path(self.tempdir.name) / "morgana.db")
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        db.init_db()
        self.user = db.get_or_create_user("ruben")
        self.other = db.get_or_create_user("otra")

    def test_event_pages_are_private_filtered_and_do_not_repeat_cursor(self):
        db.log_event(
            "tarea_creada",
            self.user["id"],
            task_id="task-1",
            prompt="dato privado",
        )
        db.log_event(
            "archivo_subido", self.user["id"], file_id="file-1", size_bytes=8
        )
        db.log_event("tarea_creada", self.other["id"], task_id="foreign")

        first, cursor = db.list_events_for_user(
            self.user["id"], limit=1, before_id=None, event_types=()
        )
        second, end_cursor = db.list_events_for_user(
            self.user["id"], limit=1, before_id=cursor, event_types=()
        )
        task_events, _ = db.list_events_for_user(
            self.user["id"],
            limit=10,
            before_id=None,
            event_types=("tarea_creada",),
        )

        self.assertEqual(
            [row["tipo"] for row in first + second],
            ["archivo_subido", "tarea_creada"],
        )
        self.assertIsNotNone(cursor)
        self.assertIsNone(end_cursor)
        self.assertEqual([row["tipo"] for row in task_events], ["tarea_creada"])
        self.assertNotIn("foreign", repr(first + second + task_events))

    def test_summary_counts_only_the_requested_user(self):
        active = db.create_task(self.user["id"], "activa", "C:/ws/alpha")
        waiting = db.create_task(self.user["id"], "espera", "C:/ws/alpha")
        completed = db.create_task(self.user["id"], "hecha", "C:/ws/alpha")
        db.update_task(waiting["id"], estado="esperando_aprobacion")
        db.update_task(completed["id"], estado="completada")
        foreign = db.create_task(self.other["id"], "ajena", "C:/ws/beta")
        db.update_task(foreign["id"], estado="completada")
        db.create_managed_file(
            self.user["id"], "informe.txt", "blob-1", "text/plain", 123, "abc"
        )
        db.create_managed_file(
            self.other["id"], "otro.txt", "blob-2", "text/plain", 999, "def"
        )
        db.upsert_device("device-own", self.user["id"], "pc", "Portátil")
        db.upsert_device("device-other", self.other["id"], "movil", "Móvil")

        summary = db.activity_summary(self.user["id"], time.time() - 120)

        self.assertEqual(summary["active_tasks"], 2)
        self.assertEqual(summary["awaiting_approval"], 1)
        self.assertEqual(summary["completed_tasks"], 1)
        self.assertEqual(summary["managed_storage_bytes"], 123)
        self.assertEqual(summary["known_devices"], 1)
        self.assertEqual(summary["recent_devices"], 1)
        self.assertIsNotNone(active)

    def test_public_event_projection_drops_internal_payload_and_bad_json(self):
        from app import activity

        task = db.create_task(
            self.user["id"], "prompt que no debe salir", "C:/private/morgana"
        )
        event = {
            "id": 7,
            "ts": 8.0,
            "user_id": self.user["id"],
            "tipo": "tarea_creada",
            "payload": (
                '{"task_id":"%s","prompt":"secreto",'
                '"workspace":"C:/private/morgana"}' % task["id"]
            ),
        }

        item = activity.serialize_event(event, self.user["id"])
        malformed = activity.serialize_event(
            {**event, "id": 8, "tipo": "evento_futuro", "payload": "{"},
            self.user["id"],
        )

        self.assertEqual(
            item,
            {
                "id": 7,
                "tipo": "tarea_creada",
                "categoria": "tareas",
                "titulo": "Tarea creada",
                "detalle": "morgana · Pendiente",
                "creado_en": 8.0,
                "enlace": f"/tareas/{task['id']}",
            },
        )
        self.assertNotIn("secreto", repr(item))
        self.assertNotIn("workspace", repr(item))
        self.assertEqual(malformed["titulo"], "Actividad registrada")
        self.assertIsNone(malformed["enlace"])

    def test_task_link_is_omitted_for_another_users_task(self):
        from app import activity

        task = db.create_task(self.other["id"], "ajena", "C:/private/otro")
        item = activity.serialize_event(
            {
                "id": 9,
                "ts": 10.0,
                "tipo": "tarea_completada",
                "payload": '{"task_id":"%s"}' % task["id"],
            },
            self.user["id"],
        )

        self.assertIsNone(item["enlace"])
        self.assertEqual(item["detalle"], "Tarea del historial")

    def test_skill_event_uses_allowlisted_manifest_metadata(self):
        from app import activity, skills

        skill = skills.create_skill(
            self.user,
            {
                "name": "Preparar informe",
                "slug": "preparar-informe",
                "description": "Convierte notas dispersas en un informe breve y accionable.",
                "instructions": (
                    "Resume los hechos, separa los riesgos y termina con tres "
                    "acciones concretas."
                ),
                "examples": ["Prepara el informe semanal"],
                "tool_ids": [],
                "scope": "personal",
            },
        )
        item = activity.serialize_event(
            {
                "id": 11,
                "ts": 12.0,
                "tipo": "skill_created",
                "payload": (
                    '{"skill_id":"%s","instructions":"dato secreto",'
                    '"request":"petición privada"}' % skill["id"]
                ),
            },
            self.user["id"],
        )

        self.assertEqual(item["categoria"], "herramientas")
        self.assertEqual(item["titulo"], "Skill creada")
        self.assertEqual(item["detalle"], "Preparar informe · v1 · Personal")
        self.assertEqual(item["enlace"], "/skills")
        self.assertNotIn("secreto", repr(item))
        self.assertNotIn("privada", repr(item))

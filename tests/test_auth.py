import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import jwt

from app import auth, db
from app.config import settings


class AuthTests(TestCase):
    def test_hash_y_verificacion_bcrypt(self):
        password_hash = auth.hash_password("un-secreto-seguro")

        self.assertNotEqual(password_hash, "un-secreto-seguro")
        self.assertTrue(password_hash.startswith("$2"))
        self.assertTrue(auth.verify_password("un-secreto-seguro", password_hash))
        self.assertFalse(auth.verify_password("incorrecta", password_hash))

    def test_hash_rechaza_password_vacia(self):
        with self.assertRaisesRegex(ValueError, "vacía"):
            auth.hash_password("")

    def test_token_incluye_usuario_y_expira(self):
        with patch.object(settings, "jwt_secret", "secreto-test-de-al-menos-32-bytes"), patch.object(
            settings, "jwt_expiration_days", 30
        ):
            token = auth.create_access_token("usuario-1")
            payload = auth.decode_access_token(token)

        self.assertEqual(payload["sub"], "usuario-1")
        self.assertGreater(payload["exp"], time.time())

    def test_token_con_firma_incorrecta_es_invalido(self):
        token = jwt.encode(
            {"sub": "usuario-1", "exp": int(time.time()) + 60},
            "otro-secreto-de-al-menos-32-bytes",
            algorithm="HS256",
        )
        with patch.object(settings, "jwt_secret", "secreto-test-de-al-menos-32-bytes"):
            with self.assertRaises(auth.InvalidTokenError):
                auth.decode_access_token(token)

    def test_no_emite_token_sin_secret(self):
        with patch.object(settings, "jwt_secret", ""):
            with self.assertRaisesRegex(RuntimeError, "JWT_SECRET"):
                auth.create_access_token("usuario-1")


class AuthDatabaseTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = str(Path(self.tempdir.name) / "morgana.db")
        self.settings_patch = patch.object(settings, "db_path", self.db_path)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_init_db_migra_users_existente(self):
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    nombre TEXT UNIQUE NOT NULL,
                    telegram_chat_id INTEGER UNIQUE,
                    linux_user TEXT,
                    creado_en REAL NOT NULL
                )
                """
            )

        db.init_db()

        with closing(sqlite3.connect(self.db_path)) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(users)")
            }
        self.assertIn("password_hash", columns)

    def test_busca_usuario_y_fija_hash(self):
        db.init_db()
        user = db.get_or_create_user("ruben")

        db.set_password_hash(user["id"], "hash-bcrypt")

        stored = db.get_user_by_nombre("ruben")
        self.assertEqual(stored["id"], user["id"])
        self.assertEqual(stored["password_hash"], "hash-bcrypt")
        self.assertIsNone(db.get_user_by_nombre("RUBEN"))

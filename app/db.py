"""Base de datos SQLite de Morgana."""
import sqlite3
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .claude_models import DEFAULT_CLAUDE_MODEL
from .config import settings

# Estados posibles de una tarea agéntica
ESTADOS = ("pendiente", "planificando", "esperando_aprobacion",
           "ejecutando", "completada", "rechazada", "error")
ESTADOS_VIVOS = ("pendiente", "planificando", "esperando_aprobacion",
                 "ejecutando")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            nombre      TEXT UNIQUE NOT NULL,
            telegram_chat_id INTEGER UNIQUE,
            password_hash TEXT,
            -- fase 2: linux_user, preferencias, skills activos
            linux_user  TEXT,
            creado_en   REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS devices (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL REFERENCES users(id),
            tipo        TEXT NOT NULL
                        CHECK (tipo IN ('movil', 'pc', 'kiosko', 'telegram')),
            nombre      TEXT,
            last_seen   REAL NOT NULL,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL REFERENCES users(id),
            prompt      TEXT NOT NULL,
            estado      TEXT NOT NULL,
            plan        TEXT,           -- plan generado por el agente (markdown)
            resultado   TEXT,           -- resumen final tras ejecutar
            workspace   TEXT,           -- directorio sobre el que trabaja
            modelo      TEXT NOT NULL DEFAULT 'claude-sonnet-5',
            creado_en   REAL NOT NULL,
            actualizado_en REAL NOT NULL
        );

        -- Log de eventos append-only: la decisión barata que nos deja
        -- estudiar el uso del sistema más adelante (ángulo investigación).
        CREATE TABLE IF NOT EXISTS events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        REAL NOT NULL,
            user_id   TEXT,
            tipo      TEXT NOT NULL,
            payload   TEXT NOT NULL    -- JSON
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id                  TEXT PRIMARY KEY,
            user_id             TEXT NOT NULL REFERENCES users(id),
            titulo              TEXT,
            estado              TEXT NOT NULL
                                CHECK (estado IN ('activa', 'archivada')),
            resumen_acumulativo TEXT,
            created_at          REAL NOT NULL,
            updated_at          REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id),
            role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content         TEXT NOT NULL,
            origen          TEXT NOT NULL
                            CHECK (origen IN ('pwa', 'telegram', 'cara')),
            client_ref      TEXT,
            tokens_aprox    INTEGER,
            created_at      REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
            ON messages(conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_conversations_user_estado
            ON conversations(user_id, estado);
        CREATE INDEX IF NOT EXISTS idx_devices_user_last_seen
            ON devices(user_id, last_seen);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_one_active_user
            ON conversations(user_id) WHERE estado = 'activa';
        """)
        columnas = {
            row["name"] for row in c.execute("PRAGMA table_info(users)").fetchall()
        }
        if "password_hash" not in columnas:
            c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        task_columns = {
            row["name"] for row in c.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "modelo" not in task_columns:
            c.execute(
                "ALTER TABLE tasks ADD COLUMN modelo TEXT NOT NULL "
                "DEFAULT 'claude-sonnet-5'"
            )
        message_columns = {
            row["name"] for row in c.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "client_ref" not in message_columns:
            c.execute("ALTER TABLE messages ADD COLUMN client_ref TEXT")
        c.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_conversation_client_ref
               ON messages(conversation_id, client_ref)
               WHERE client_ref IS NOT NULL"""
        )


def log_event(tipo: str, user_id: str | None = None, **payload) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO events (ts, user_id, tipo, payload) VALUES (?, ?, ?, ?)",
            (time.time(), user_id, tipo, json.dumps(payload, ensure_ascii=False)),
        )


# ---------- Usuarios ----------

def get_or_create_user(nombre: str, telegram_chat_id: int | None = None) -> dict:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE nombre = ?", (nombre,)).fetchone()
        if row:
            if telegram_chat_id and not row["telegram_chat_id"]:
                c.execute("UPDATE users SET telegram_chat_id = ? WHERE id = ?",
                          (telegram_chat_id, row["id"]))
                row = c.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            return dict(row)
        uid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO users (id, nombre, telegram_chat_id, creado_en) VALUES (?, ?, ?, ?)",
            (uid, nombre, telegram_chat_id, time.time()),
        )
        return dict(c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())


def get_user_by_id(user_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_nombre(nombre: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE nombre = ?", (nombre,)).fetchone()
        return dict(row) if row else None


def set_password_hash(user_id: str, password_hash: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )


def user_by_chat_id(chat_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE telegram_chat_id = ?", (chat_id,)).fetchone()
        return dict(row) if row else None


def first_telegram_user() -> dict | None:
    """Devuelve el propietario que reclamó primero el canal de Telegram."""
    with _conn() as c:
        row = c.execute(
            """SELECT * FROM users
               WHERE telegram_chat_id IS NOT NULL
               ORDER BY creado_en ASC, id ASC
               LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None


# ---------- Dispositivos ----------

DEVICE_TYPES = {"movil", "pc", "kiosko", "telegram"}


def upsert_device(
    device_id: str,
    user_id: str,
    tipo: str,
    nombre: str | None = None,
) -> bool:
    """Registra actividad sin permitir que otro usuario reclame el mismo id."""
    if tipo not in DEVICE_TYPES:
        raise ValueError(f"Tipo de dispositivo no soportado: {tipo}")
    now = time.time()
    with _conn() as c:
        existing = c.execute(
            "SELECT user_id FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        if existing and existing["user_id"] != user_id:
            return False
        c.execute(
            """INSERT INTO devices
               (id, user_id, tipo, nombre, last_seen, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   tipo = excluded.tipo,
                   nombre = COALESCE(excluded.nombre, devices.nombre),
                   last_seen = excluded.last_seen""",
            (device_id, user_id, tipo, nombre, now, now),
        )
    return True


def touch_device(device_id: str, user_id: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE devices SET last_seen = ? WHERE id = ? AND user_id = ?",
            (time.time(), device_id, user_id),
        )


# ---------- Tareas ----------

def create_task(
    user_id: str,
    prompt: str,
    workspace: str,
    modelo: str = DEFAULT_CLAUDE_MODEL,
) -> dict:
    tid = str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO tasks
               (id, user_id, prompt, estado, workspace, modelo, creado_en, actualizado_en)
               VALUES (?, ?, ?, 'pendiente', ?, ?, ?, ?)""",
            (tid, user_id, prompt, workspace, modelo, now, now),
        )
        return dict(c.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone())


def update_task(task_id: str, **campos) -> None:
    if not campos:
        return
    campos["actualizado_en"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in campos)
    with _conn() as c:
        c.execute(f"UPDATE tasks SET {sets} WHERE id = ?", (*campos.values(), task_id))


def transition_task(task_id: str, from_estado: str, to_estado: str) -> bool:
    """Cambia el estado de forma atómica si sigue siendo el esperado."""
    with _conn() as c:
        cursor = c.execute(
            """UPDATE tasks SET estado = ?, actualizado_en = ?
               WHERE id = ? AND estado = ?""",
            (to_estado, time.time(), task_id, from_estado),
        )
        return cursor.rowcount == 1


def get_task(task_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def list_tasks(
    user_id: str,
    estado: str | None = None,
    proyecto: str | None = None,
    limite: int = 50,
) -> list[dict]:
    query = "SELECT * FROM tasks WHERE user_id = ?"
    params: list[object] = [user_id]
    if estado:
        query += " AND estado = ?"
        params.append(estado)
    query += " ORDER BY creado_en DESC"

    with _conn() as c:
        rows = [dict(row) for row in c.execute(query, params).fetchall()]
    if proyecto:
        buscado = proyecto.casefold()
        rows = [
            task
            for task in rows
            if task.get("workspace")
            and Path(task["workspace"]).name.casefold() == buscado
        ]
    return rows[:limite]


def get_tasks_by_estado(*estados: str) -> list[dict]:
    with _conn() as c:
        placeholders = ", ".join("?" for _ in estados)
        rows = c.execute(
            f"SELECT * FROM tasks WHERE estado IN ({placeholders})", estados
        ).fetchall()
        return [dict(row) for row in rows]


def list_live_tasks(user_id: str) -> list[dict]:
    """Lista tareas no terminales, priorizando las que esperan aprobación."""
    placeholders = ", ".join("?" for _ in ESTADOS_VIVOS)
    with _conn() as c:
        rows = c.execute(
            f"""SELECT * FROM tasks
                WHERE user_id = ? AND estado IN ({placeholders})
                ORDER BY CASE estado WHEN 'esperando_aprobacion' THEN 0 ELSE 1 END,
                         actualizado_en DESC""",
            (user_id, *ESTADOS_VIVOS),
        ).fetchall()
        return [dict(row) for row in rows]


# ---------- Conversaciones rápidas ----------

def get_active_conversation(user_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM conversations WHERE user_id = ? AND estado = 'activa'",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_or_create_active_conversation(user_id: str) -> dict:
    """Devuelve la conversación activa y la crea si aún no existe."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM conversations WHERE user_id = ? AND estado = 'activa'",
            (user_id,),
        ).fetchone()
        if row:
            return dict(row)

        conversation_id = str(uuid.uuid4())
        now = time.time()
        c.execute(
            """INSERT OR IGNORE INTO conversations
               (id, user_id, estado, created_at, updated_at)
               VALUES (?, ?, 'activa', ?, ?)""",
            (conversation_id, user_id, now, now),
        )
        row = c.execute(
            "SELECT * FROM conversations WHERE user_id = ? AND estado = 'activa'",
            (user_id,),
        ).fetchone()
        if not row:
            raise RuntimeError("No se pudo crear la conversación activa")
        return dict(row)


def reset_active_conversation(user_id: str) -> dict:
    """Archiva la conversación actual y crea una activa vacía en una transacción."""
    conversation_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        c.execute(
            """UPDATE conversations SET estado = 'archivada', updated_at = ?
               WHERE user_id = ? AND estado = 'activa'""",
            (now, user_id),
        )
        c.execute(
            """INSERT INTO conversations
               (id, user_id, estado, created_at, updated_at)
               VALUES (?, ?, 'activa', ?, ?)""",
            (conversation_id, user_id, now, now),
        )
        row = c.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row)


def add_conversation_message(
    conversation_id: str,
    role: str,
    content: str,
    origin: str,
    client_ref: str | None = None,
) -> dict:
    now = time.time()
    tokens_aprox = len(content) // 4
    with _conn() as c:
        cursor = c.execute(
            """INSERT INTO messages
               (conversation_id, role, content, origen, client_ref,
                tokens_aprox, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conversation_id, role, content, origin, client_ref, tokens_aprox, now),
        )
        c.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        row = c.execute(
            "SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return dict(row)


def list_active_conversation_messages(
    user_id: str,
    limit: int = 50,
    before_id: int | None = None,
) -> list[dict]:
    """Devuelve los mensajes más recientes de la activa, en orden cronológico."""
    params: list[object] = [user_id]
    before_clause = ""
    if before_id is not None:
        before_clause = "AND m.id < ?"
        params.append(before_id)
    params.append(limit)
    with _conn() as c:
        rows = c.execute(
            f"""SELECT m.* FROM messages AS m
                JOIN conversations AS c ON c.id = m.conversation_id
                WHERE c.user_id = ? AND c.estado = 'activa' {before_clause}
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT ?""",
            params,
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def conversation_messages_page(
    user_id: str,
    limit: int = 50,
    before_id: int | None = None,
    after_id: int | None = None,
) -> dict:
    """Devuelve una página y detecta si el cursor quedó en otra conversación."""
    conversation = get_or_create_active_conversation(user_id)
    conversation_changed = False

    if after_id is not None:
        with _conn() as c:
            cursor = c.execute(
                """SELECT m.conversation_id, c.user_id
                   FROM messages AS m
                   JOIN conversations AS c ON c.id = m.conversation_id
                   WHERE m.id = ?""",
                (after_id,),
            ).fetchone()
            conversation_changed = not (
                cursor
                and cursor["user_id"] == user_id
                and cursor["conversation_id"] == conversation["id"]
            )
            if not conversation_changed:
                rows = c.execute(
                    """SELECT * FROM messages
                       WHERE conversation_id = ? AND id > ?
                       ORDER BY created_at ASC, id ASC
                       LIMIT ?""",
                    (conversation["id"], after_id, limit),
                ).fetchall()
                messages = [dict(row) for row in rows]
            else:
                rows = c.execute(
                    """SELECT * FROM messages
                       WHERE conversation_id = ?
                       ORDER BY created_at DESC, id DESC
                       LIMIT ?""",
                    (conversation["id"], limit),
                ).fetchall()
                messages = [dict(row) for row in reversed(rows)]
    else:
        messages = list_active_conversation_messages(user_id, limit, before_id)

    return {
        "conversation_id": conversation["id"],
        "conversation_created_at": conversation["created_at"],
        "conversation_changed": conversation_changed,
        "messages": messages,
    }


def list_context_messages(conversation_id: str, token_budget: int) -> list[dict]:
    """Lee desde el final hasta llenar el presupuesto, sin partir mensajes."""
    selected: list[dict] = []
    used_tokens = 0
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM messages WHERE conversation_id = ?
               ORDER BY created_at DESC, id DESC""",
            (conversation_id,),
        )
        for row in rows:
            message = dict(row)
            tokens = message.get("tokens_aprox")
            if tokens is None:
                tokens = len(message["content"]) // 4
            if used_tokens + tokens > token_budget:
                break
            selected.append(message)
            used_tokens += tokens
    selected.reverse()
    return selected

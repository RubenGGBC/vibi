"""Base de datos SQLite de Vibi."""
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


# Lo que espera una escritura a que le suelten la base antes de rendirse. El
# valor por defecto de `sqlite3.connect` son 5 s, y el 30/08/2026 se quedaron
# cortos: con un turno de `agy` leyendo y escribiendo a la vez, un latido del
# companion tardaba una mediana de 1,3 s y llegaba a 3,9 s. En WAL sobra de
# largo, pero el margen no cuesta nada y es lo que separa un latido lento de un
# WebSocket muerto.
BUSY_TIMEOUT_MS = 15_000


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Una conexión por consulta, en WAL y sin fsync por commit.

    Los tres `PRAGMA` no son decoración; cada uno tapa un fallo que se vio en
    producción.

    `journal_mode=WAL` es el importante. Con el modo `delete` de por defecto un
    lector bloquea al escritor durante toda su transacción, así que las
    escrituras de latido —`upsert_device`, `touch_device`, `touch_node`— se
    comían el tiempo del turno que estuviera en marcha. Cuando pasaban del
    `busy_timeout` saltaba `database is locked`, y el manejador del WebSocket
    que lo pedía lo daba por roto y lo cerraba. Eso es lo que desconectaba al
    nodo PC en mitad de un turno:

        17:42:18  WebSocket de nodo interrumpido  <- locked en `touch_node`
        17:42:19  El nodo PC no pudo abrir el navegador: PC se desconectó
                  antes de recibir la orden.

    y `agy` se quedaba esperando una herramienta que ya no iba a contestar. En
    el `core.log` había 222 de esos, 31 en un solo día.

    Medido con seis lectores y cuatro escritores contra la base real (18 MB):
    la mediana de un latido pasa de 1.335 ms a 12 ms.

    `synchronous=NORMAL` es lo que hace que WAL merezca la pena aquí: con
    `FULL` cada commit fuerza un fsync, y este disco va al 98%. En WAL lo único
    que arriesga NORMAL es perder las últimas transacciones ante un corte de
    corriente —la base no se corrompe—, y lo que hay en juego son latidos y
    mensajes de chat, no dinero.

    `foreign_keys` es por conexión, no del fichero: sin repetirlo aquí, cada
    conexión nueva volvería a nacer sin integridad referencial.
    """
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    # Fuera de transacción a propósito: `journal_mode` no se puede cambiar
    # dentro de una, y `with conn:` abre la suya más abajo.
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
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

        -- Un nodo es una máquina que ejecuta órdenes (PC main, MacBook), no
        -- una ventana del navegador: por eso tiene token propio y vive aparte
        -- de `devices`. La misma máquina puede aparecer en las dos tablas.
        CREATE TABLE IF NOT EXISTS nodes (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL REFERENCES users(id),
            nombre      TEXT NOT NULL,
            plataforma  TEXT NOT NULL,
            token_hash  TEXT NOT NULL,
            estado      TEXT NOT NULL DEFAULT 'activo'
                        CHECK (estado IN ('activo', 'revocado')),
            capacidades TEXT NOT NULL DEFAULT '[]',
            last_seen   REAL,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS node_orders (
            id           TEXT PRIMARY KEY,
            node_id      TEXT NOT NULL REFERENCES nodes(id),
            user_id      TEXT NOT NULL REFERENCES users(id),
            capability   TEXT NOT NULL,
            arguments    TEXT NOT NULL DEFAULT '{}',
            estado       TEXT NOT NULL
                         CHECK (estado IN ('pendiente', 'entregada', 'ok',
                                           'error', 'caducada')),
            resultado    TEXT,
            expires_at   REAL NOT NULL,
            created_at   REAL NOT NULL,
            delivered_at REAL,
            completed_at REAL
        );

        -- Un archivo viajando entre dos extremos del usuario. Existe porque un
        -- envío son dos órdenes distintas (subir en el origen, bajar en el
        -- destino) más un blob intermedio, y algo tiene que correlacionarlos.
        -- Los extremos que no son un nodo (Telegram, el propio Vibi) dejan
        -- su columna a NULL.
        CREATE TABLE IF NOT EXISTS transfers (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL REFERENCES users(id),
            origen_node_id  TEXT REFERENCES nodes(id),
            destino_node_id TEXT REFERENCES nodes(id),
            destino_canal   TEXT,
            file_id         TEXT REFERENCES files(id),
            nombre          TEXT NOT NULL,
            ruta_origen     TEXT,
            bytes_esperados INTEGER,
            bytes_recibidos INTEGER NOT NULL DEFAULT 0,
            estado          TEXT NOT NULL
                            CHECK (estado IN ('esperando_origen', 'en_servidor',
                                              'entregando', 'entregado',
                                              'error', 'caducada')),
            error           TEXT,
            expires_at      REAL NOT NULL,
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL
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

        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL REFERENCES users(id),
            nombre      TEXT NOT NULL,
            slug        TEXT NOT NULL,
            descripcion TEXT NOT NULL DEFAULT '',
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL,
            UNIQUE (user_id, slug)
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id                  TEXT PRIMARY KEY,
            user_id             TEXT NOT NULL REFERENCES users(id),
            project_id          TEXT REFERENCES projects(id),
            titulo              TEXT,
            estado              TEXT NOT NULL
                                CHECK (estado IN ('activa', 'archivada')),
            resumen_acumulativo TEXT,
            claude_session_id   TEXT,
            thinking_enabled    INTEGER NOT NULL DEFAULT 0
                                CHECK (thinking_enabled IN (0, 1)),
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

        CREATE TABLE IF NOT EXISTS message_attachments (
            message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            file_id     TEXT NOT NULL REFERENCES files(id),
            created_at  REAL NOT NULL,
            PRIMARY KEY (message_id, file_id)
        );

        CREATE TABLE IF NOT EXISTS files (
            id            TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL REFERENCES users(id),
            project_id    TEXT REFERENCES projects(id),
            source        TEXT NOT NULL CHECK (source IN ('managed', 'workspace')),
            name          TEXT NOT NULL,
            relative_path TEXT,
            storage_key   TEXT,
            media_type    TEXT,
            size_bytes    INTEGER NOT NULL CHECK (size_bytes >= 0),
            sha256        TEXT,
            content_text  TEXT,
            content_indexed_at REAL,
            modified_at   REAL NOT NULL,
            created_at    REAL NOT NULL,
            deleted_at    REAL,
            CHECK (
                (source = 'managed' AND storage_key IS NOT NULL) OR
                (source = 'workspace' AND relative_path IS NOT NULL)
            )
        );

        CREATE TABLE IF NOT EXISTS tools (
            id             TEXT PRIMARY KEY,
            scope          TEXT NOT NULL CHECK (scope IN ('personal', 'lab')),
            owner_user_id  TEXT REFERENCES users(id),
            name           TEXT NOT NULL,
            description    TEXT NOT NULL,
            primitive_id   TEXT NOT NULL,
            bound_arguments TEXT NOT NULL DEFAULT '{}',
            enabled        INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            source         TEXT NOT NULL DEFAULT 'human'
                           CHECK (source IN ('human', 'agent')),
            created_at     REAL NOT NULL,
            updated_at     REAL NOT NULL,
            CHECK (
                (scope = 'personal' AND owner_user_id IS NOT NULL) OR
                (scope = 'lab' AND owner_user_id IS NULL)
            )
        );

        -- Una herramienta que Vibi se escribió a sí misma: un guion de
        -- Python que resuelve algo repetitivo. Vive aparte de `tools` a
        -- propósito. Una fila de `tools` es una composición sobre una
        -- primitiva del catálogo cerrado y no puede ejecutar código; esta sí
        -- lo lleva dentro, y mezclarlas en la misma tabla habría convertido
        -- ese límite en una columna opcional que es fácil olvidar mirar.
        CREATE TABLE IF NOT EXISTS tool_scripts (
            id             TEXT PRIMARY KEY,
            owner_user_id  TEXT NOT NULL REFERENCES users(id),
            slug           TEXT NOT NULL,
            name           TEXT NOT NULL,
            description    TEXT NOT NULL,
            parametros     TEXT NOT NULL DEFAULT '[]',
            codigo         TEXT NOT NULL,
            peticion       TEXT NOT NULL,
            modelo         TEXT NOT NULL,
            comprobacion   TEXT NOT NULL DEFAULT '{}',
            enabled        INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            version        INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            created_at     REAL NOT NULL,
            updated_at     REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tool_invocations (
            id            TEXT PRIMARY KEY,
            tool_id       TEXT NOT NULL,
            actor_user_id TEXT NOT NULL REFERENCES users(id),
            status        TEXT NOT NULL
                          CHECK (status IN ('running', 'succeeded', 'failed', 'denied')),
            error_code    TEXT,
            requested_at  REAL NOT NULL,
            completed_at  REAL,
            duration_ms   INTEGER
        );

        CREATE TABLE IF NOT EXISTS skills (
            id             TEXT PRIMARY KEY,
            scope          TEXT NOT NULL CHECK (scope IN ('personal', 'lab')),
            owner_user_id  TEXT REFERENCES users(id),
            slug           TEXT NOT NULL,
            name           TEXT NOT NULL,
            description    TEXT NOT NULL,
            instructions   TEXT NOT NULL,
            examples       TEXT NOT NULL DEFAULT '[]',
            tool_ids       TEXT NOT NULL DEFAULT '[]',
            enabled        INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
            version        INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            created_at     REAL NOT NULL,
            updated_at     REAL NOT NULL,
            CHECK (
                (scope = 'personal' AND owner_user_id IS NOT NULL) OR
                (scope = 'lab' AND owner_user_id IS NULL)
            )
        );

        CREATE TABLE IF NOT EXISTS skill_versions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id    TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            version     INTEGER NOT NULL CHECK (version >= 1),
            snapshot    TEXT NOT NULL,
            created_at  REAL NOT NULL,
            UNIQUE(skill_id, version)
        );

        CREATE TABLE IF NOT EXISTS user_ai_settings (
            user_id         TEXT PRIMARY KEY REFERENCES users(id),
            chat_provider   TEXT NOT NULL,
            chat_model      TEXT NOT NULL,
            tools_provider  TEXT NOT NULL,
            tools_model     TEXT NOT NULL,
            speech_provider TEXT NOT NULL,
            speech_model    TEXT NOT NULL,
            agent_provider  TEXT NOT NULL,
            agent_model     TEXT NOT NULL,
            updated_at      REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS provider_credentials (
            user_id          TEXT NOT NULL REFERENCES users(id),
            provider         TEXT NOT NULL,
            encrypted_api_key TEXT NOT NULL,
            updated_at       REAL NOT NULL,
            PRIMARY KEY (user_id, provider)
        );

        -- Lo que el usuario ha mandado callar de sus notificaciones. Va por
        -- usuario y no por nodo: silenciar las promociones de Steam en el
        -- portátil tiene que callarlas también en el sobremesa.
        CREATE TABLE IF NOT EXISTS avisos_silenciados (
            id       TEXT PRIMARY KEY,
            user_id  TEXT NOT NULL REFERENCES users(id),
            app      TEXT NOT NULL DEFAULT '',
            patron   TEXT NOT NULL DEFAULT '',
            creado   REAL NOT NULL
        );

        -- Lo que el usuario ya ha dicho que Vibi puede (o no puede) hacer sola
        -- cuando llega una notificación. Vive en su propia tabla y no en la
        -- memoria del motor a propósito: un permiso tiene que poder listarse y
        -- retirarse con certeza, y un recuerdo interpretado no da esa garantía.
        -- Se guarda también el «no», que es lo que evita volver a preguntar lo
        -- mismo cada vez que llega la misma notificación.
        CREATE TABLE IF NOT EXISTS avisos_permisos (
            id        TEXT PRIMARY KEY,
            user_id   TEXT NOT NULL REFERENCES users(id),
            app       TEXT NOT NULL DEFAULT '',
            accion    TEXT NOT NULL,
            permitido INTEGER NOT NULL,
            creado    REAL NOT NULL,
            UNIQUE (user_id, app, accion)
        );

        -- Lo que Vibi ha aprendido sobre cómo se maneja cada aplicación. Vive
        -- aquí y no en `skills` porque una skill la escribe el usuario y se
        -- invoca a mano, y una receta la aprende Vibi y se carga sola. La
        -- lógica —y por qué solo se guarda lo verificado— está en `recetas.py`.
        CREATE TABLE IF NOT EXISTS recetas (
            app            TEXT PRIMARY KEY,
            via            TEXT NOT NULL CHECK (via IN ('cdp', 'arbol')),
            contenido      TEXT NOT NULL,
            comprobacion   TEXT NOT NULL DEFAULT '',
            fallos         INTEGER NOT NULL DEFAULT 0,
            verificada_en  REAL NOT NULL,
            creada_en      REAL NOT NULL
        );

        -- Lo que Vibi se ha quedado mirando por encargo tuyo. La sonda que la
        -- alimenta vive en el nodo y es tonta a propósito; el juicio de si un
        -- cambio merece interrumpirte está en `vigilancias.py`. `que_espero`
        -- guarda tu frase tal cual la dijiste: es lo único contra lo que se
        -- puede juzgar después si lo que cambió era lo que esperabas.
        CREATE TABLE IF NOT EXISTS vigilancias (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            node_id     TEXT NOT NULL,
            sonda       TEXT NOT NULL
                        CHECK (sonda IN (
                            'proceso', 'archivo', 'web', 'ventana', 'actividad'
                        )),
            parametros  TEXT NOT NULL DEFAULT '{}',
            que_espero  TEXT NOT NULL,
            intervalo   REAL NOT NULL,
            estado      TEXT NOT NULL DEFAULT 'viva',
            novedades   INTEGER NOT NULL DEFAULT 0,
            creada_en   REAL NOT NULL,
            caduca_en   REAL NOT NULL,
            cerrada_en  REAL,
            desenlace   TEXT NOT NULL DEFAULT '',
            continuacion TEXT NOT NULL DEFAULT '',
            conversation_id TEXT NOT NULL DEFAULT '',
            continuacion_estado TEXT NOT NULL DEFAULT '',
            continuada_en REAL
        );

        CREATE INDEX IF NOT EXISTS idx_vigilancias_user_estado
            ON vigilancias(user_id, estado);
        CREATE INDEX IF NOT EXISTS idx_vigilancias_node_estado
            ON vigilancias(node_id, estado);
        CREATE INDEX IF NOT EXISTS idx_avisos_silenciados_user
            ON avisos_silenciados(user_id);
        CREATE INDEX IF NOT EXISTS idx_avisos_permisos_user
            ON avisos_permisos(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
            ON messages(conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_conversations_user_estado
            ON conversations(user_id, estado);
        CREATE INDEX IF NOT EXISTS idx_devices_user_last_seen
            ON devices(user_id, last_seen);
        CREATE INDEX IF NOT EXISTS idx_events_user_id
            ON events(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_files_user_created
            ON files(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_projects_user_updated
            ON projects(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_message_attachments_file
            ON message_attachments(file_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_files_workspace_path
            ON files(user_id, relative_path)
            WHERE source = 'workspace' AND deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_transfers_user_created
            ON transfers(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_tools_owner_scope
            ON tools(owner_user_id, scope, enabled);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_scripts_owner_slug
            ON tool_scripts(owner_user_id, slug);
        CREATE INDEX IF NOT EXISTS idx_tool_invocations_actor_requested
            ON tool_invocations(actor_user_id, requested_at DESC);
        CREATE INDEX IF NOT EXISTS idx_tool_invocations_actor_tool_requested
            ON tool_invocations(actor_user_id, tool_id, requested_at DESC);
        CREATE INDEX IF NOT EXISTS idx_skills_owner_scope
            ON skills(owner_user_id, scope, enabled, updated_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_personal_slug
            ON skills(owner_user_id, slug) WHERE scope = 'personal';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_lab_slug
            ON skills(slug) WHERE scope = 'lab';
        CREATE INDEX IF NOT EXISTS idx_skill_versions_skill_version
            ON skill_versions(skill_id, version DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_one_active_user
            ON conversations(user_id) WHERE estado = 'activa';
        """)
        columnas = {
            row["name"] for row in c.execute("PRAGMA table_info(users)").fetchall()
        }
        if "password_hash" not in columnas:
            c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        if "is_admin" not in columnas:
            c.execute(
                "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
            )
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
        conversation_columns = {
            row["name"]
            for row in c.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "claude_session_id" not in conversation_columns:
            c.execute("ALTER TABLE conversations ADD COLUMN claude_session_id TEXT")
        if "thinking_enabled" not in conversation_columns:
            c.execute(
                "ALTER TABLE conversations ADD COLUMN thinking_enabled "
                "INTEGER NOT NULL DEFAULT 0"
            )
        if "project_id" not in conversation_columns:
            c.execute(
                "ALTER TABLE conversations ADD COLUMN project_id TEXT "
                "REFERENCES projects(id)"
            )
        file_columns = {
            row["name"] for row in c.execute("PRAGMA table_info(files)").fetchall()
        }
        if "content_text" not in file_columns:
            c.execute("ALTER TABLE files ADD COLUMN content_text TEXT")
        if "content_indexed_at" not in file_columns:
            c.execute("ALTER TABLE files ADD COLUMN content_indexed_at REAL")
        if "project_id" not in file_columns:
            c.execute("ALTER TABLE files ADD COLUMN project_id TEXT REFERENCES projects(id)")
        # Estos índices dependen de project_id, añadida por ALTER TABLE arriba
        # en bases de datos preexistentes: no pueden vivir en el executescript
        # inicial porque ese corre antes de que la columna exista.
        c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_files_project_created
            ON files(project_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_conversations_project_updated
            ON conversations(project_id, updated_at DESC);
        """)
        node_columns = {
            row["name"] for row in c.execute("PRAGMA table_info(nodes)").fetchall()
        }
        # Un nodo puede seguir contestando pings y listando proyectos con el
        # shell apagado: es el interruptor para las máquinas donde no quieres
        # que Vibi ejecute nada, y el kill switch general lo baja en todas.
        if "shell_habilitado" not in node_columns:
            c.execute(
                "ALTER TABLE nodes ADD COLUMN shell_habilitado "
                "INTEGER NOT NULL DEFAULT 1"
            )
        order_columns = {
            row["name"]
            for row in c.execute("PRAGMA table_info(node_orders)").fetchall()
        }
        # `estado` sigue describiendo el viaje de la orden (pendiente, entregada,
        # ok…). La decisión humana vive aparte porque son dos ejes distintos:
        # una orden puede estar aprobada y fallar, o rechazarse sin salir de aquí.
        if "aprobacion" not in order_columns:
            c.execute(
                "ALTER TABLE node_orders ADD COLUMN aprobacion TEXT "
                "NOT NULL DEFAULT 'no_requiere'"
            )
        if "riesgo" not in order_columns:
            c.execute(
                "ALTER TABLE node_orders ADD COLUMN riesgo TEXT "
                "NOT NULL DEFAULT 'bajo'"
            )
        # Por qué se pidió confirmación: sirve para explicártelo en la UI y para
        # auditar después si el criterio fue el correcto.
        if "motivo_aprobacion" not in order_columns:
            c.execute("ALTER TABLE node_orders ADD COLUMN motivo_aprobacion TEXT")
        # `executescript` deja la conexión en autocommit y el DDL no abre una
        # transacción implícita. Desde aquí la migración de vigilancias debe ser
        # indivisible: o queda la tabla nueva con todos sus datos, o no cambia.
        if not c.in_transaction:
            c.execute("BEGIN IMMEDIATE")
        vigilancia_sql = c.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'vigilancias'"
        ).fetchone()["sql"]
        vigilancia_columns = {
            row["name"]
            for row in c.execute("PRAGMA table_info(vigilancias)").fetchall()
        }
        # SQLite no permite ampliar un CHECK con ALTER TABLE. Esta reconstrucción
        # conserva las vigilancias existentes y habilita sondas nuevas.
        if "'actividad'" not in vigilancia_sql or "'archivo'" not in vigilancia_sql:
            c.execute("DROP INDEX IF EXISTS idx_vigilancias_user_estado")
            c.execute("DROP INDEX IF EXISTS idx_vigilancias_node_estado")
            c.execute("ALTER TABLE vigilancias RENAME TO vigilancias_anterior")
            # Sentencias individuales: `executescript` haría COMMIT antes de
            # empezar y un corte podría dejar la tabla vieja solo a medio copiar.
            c.execute("""CREATE TABLE vigilancias (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                sonda TEXT NOT NULL CHECK (
                    sonda IN ('proceso', 'archivo', 'web', 'ventana', 'actividad')
                ),
                parametros TEXT NOT NULL DEFAULT '{}',
                que_espero TEXT NOT NULL,
                intervalo REAL NOT NULL,
                estado TEXT NOT NULL DEFAULT 'viva',
                novedades INTEGER NOT NULL DEFAULT 0,
                creada_en REAL NOT NULL,
                caduca_en REAL NOT NULL,
                cerrada_en REAL,
                desenlace TEXT NOT NULL DEFAULT '',
                continuacion TEXT NOT NULL DEFAULT '',
                conversation_id TEXT NOT NULL DEFAULT '',
                continuacion_estado TEXT NOT NULL DEFAULT '',
                continuada_en REAL
            )""")
            continuacion = (
                "continuacion" if "continuacion" in vigilancia_columns else "''"
            )
            conversation_id = (
                "conversation_id" if "conversation_id" in vigilancia_columns else "''"
            )
            continuacion_estado = (
                "continuacion_estado"
                if "continuacion_estado" in vigilancia_columns
                else "''"
            )
            continuada_en = (
                "continuada_en" if "continuada_en" in vigilancia_columns else "NULL"
            )
            c.execute(f"""INSERT INTO vigilancias (
                id, user_id, node_id, sonda, parametros, que_espero,
                intervalo, estado, novedades, creada_en, caduca_en,
                cerrada_en, desenlace, continuacion, conversation_id,
                continuacion_estado, continuada_en
            )
            SELECT id, user_id, node_id, sonda, parametros, que_espero,
                   intervalo, estado, novedades, creada_en, caduca_en,
                   cerrada_en, desenlace, {continuacion}, {conversation_id},
                   {continuacion_estado}, {continuada_en}
            FROM vigilancias_anterior""")
            c.execute("DROP TABLE vigilancias_anterior")
            c.execute(
                """CREATE INDEX idx_vigilancias_user_estado
                   ON vigilancias(user_id, estado)"""
            )
            c.execute(
                """CREATE INDEX idx_vigilancias_node_estado
                   ON vigilancias(node_id, estado)"""
            )
        else:
            if "continuacion" not in vigilancia_columns:
                c.execute(
                    "ALTER TABLE vigilancias ADD COLUMN continuacion TEXT "
                    "NOT NULL DEFAULT ''"
                )
            if "conversation_id" not in vigilancia_columns:
                c.execute(
                    "ALTER TABLE vigilancias ADD COLUMN conversation_id TEXT "
                    "NOT NULL DEFAULT ''"
                )
            if "continuacion_estado" not in vigilancia_columns:
                c.execute(
                    "ALTER TABLE vigilancias ADD COLUMN continuacion_estado TEXT "
                    "NOT NULL DEFAULT ''"
                )
            if "continuada_en" not in vigilancia_columns:
                c.execute("ALTER TABLE vigilancias ADD COLUMN continuada_en REAL")
        c.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_conversation_client_ref
               ON messages(conversation_id, client_ref)
               WHERE client_ref IS NOT NULL"""
        )
        # Un nombre de nodo debe ser inequívoco dentro de un usuario: es lo que
        # el modelo resuelve cuando le dices "en el MacBook". Los revocados no
        # cuentan, así que el nombre se puede reutilizar tras dar de baja uno.
        c.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_user_nombre
               ON nodes(user_id, nombre COLLATE NOCASE)
               WHERE estado = 'activo'"""
        )
        c.execute(
            """CREATE INDEX IF NOT EXISTS idx_node_orders_node_estado
               ON node_orders(node_id, estado)"""
        )
    from . import perfil  # noqa: PLC0415 - perezoso para no cerrar un ciclo
    perfil.crear_tablas()


def log_event(tipo: str, user_id: str | None = None, **payload) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO events (ts, user_id, tipo, payload) VALUES (?, ?, ?, ?)",
            (time.time(), user_id, tipo, json.dumps(payload, ensure_ascii=False)),
        )


def list_events_for_user(
    user_id: str,
    limit: int = 25,
    before_id: int | None = None,
    event_types: tuple[str, ...] = (),
) -> tuple[list[dict], int | None]:
    """Pagina el log privado por id, con cursor exclusivo y filtro opcional."""
    if not 1 <= limit <= 100:
        raise ValueError("El límite de actividad debe estar entre 1 y 100")

    query = "SELECT * FROM events WHERE user_id = ?"
    params: list[object] = [user_id]
    if before_id is not None:
        query += " AND id < ?"
        params.append(before_id)
    if event_types:
        placeholders = ", ".join("?" for _ in event_types)
        query += f" AND tipo IN ({placeholders})"
        params.extend(event_types)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit + 1)

    with _conn() as c:
        rows = [dict(row) for row in c.execute(query, params).fetchall()]

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = int(page[-1]["id"]) if has_more and page else None
    return page, next_cursor


def activity_summary(user_id: str, recent_since: float) -> dict:
    """Agrega indicadores operativos sin mezclar datos entre usuarios."""
    task_placeholders = ", ".join("?" for _ in ESTADOS_VIVOS)
    with _conn() as c:
        task_counts = c.execute(
            f"""SELECT
                    COALESCE(SUM(CASE WHEN estado IN ({task_placeholders})
                                      THEN 1 ELSE 0 END), 0) AS active_tasks,
                    COALESCE(SUM(CASE WHEN estado = 'esperando_aprobacion'
                                      THEN 1 ELSE 0 END), 0) AS awaiting_approval,
                    COALESCE(SUM(CASE WHEN estado = 'completada'
                                      THEN 1 ELSE 0 END), 0) AS completed_tasks
                FROM tasks WHERE user_id = ?""",
            (*ESTADOS_VIVOS, user_id),
        ).fetchone()
        storage = c.execute(
            """SELECT COALESCE(SUM(size_bytes), 0) AS managed_storage_bytes
               FROM files
               WHERE user_id = ? AND source = 'managed' AND deleted_at IS NULL""",
            (user_id,),
        ).fetchone()
        devices = c.execute(
            """SELECT COUNT(*) AS known_devices,
                      COALESCE(SUM(CASE WHEN last_seen >= ? THEN 1 ELSE 0 END), 0)
                          AS recent_devices
               FROM devices WHERE user_id = ?""",
            (recent_since, user_id),
        ).fetchone()

    return {
        "active_tasks": int(task_counts["active_tasks"]),
        "awaiting_approval": int(task_counts["awaiting_approval"]),
        "completed_tasks": int(task_counts["completed_tasks"]),
        "managed_storage_bytes": int(storage["managed_storage_bytes"]),
        "known_devices": int(devices["known_devices"]),
        "recent_devices": int(devices["recent_devices"]),
    }


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


def set_user_admin(user_id: str, is_admin: bool) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (int(is_admin), user_id),
        )


def get_user_ai_settings(user_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM user_ai_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def list_users_with_chat_provider(provider: str) -> list[dict]:
    """Quién tiene elegido ese motor de chat. Se usa para precalentarlo."""
    with _conn() as c:
        rows = c.execute(
            "SELECT u.id, u.nombre FROM users u"
            " JOIN user_ai_settings s ON s.user_id = u.id"
            " WHERE s.chat_provider = ?",
            (provider,),
        ).fetchall()
        return [dict(row) for row in rows]


def upsert_user_ai_settings(user_id: str, values: dict) -> dict:
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO user_ai_settings
               (user_id, chat_provider, chat_model, tools_provider, tools_model,
                speech_provider, speech_model, agent_provider, agent_model,
                updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 chat_provider = excluded.chat_provider,
                 chat_model = excluded.chat_model,
                 tools_provider = excluded.tools_provider,
                 tools_model = excluded.tools_model,
                 speech_provider = excluded.speech_provider,
                 speech_model = excluded.speech_model,
                 agent_provider = excluded.agent_provider,
                 agent_model = excluded.agent_model,
                 updated_at = excluded.updated_at""",
            (
                user_id,
                values["chat_provider"],
                values["chat_model"],
                values["tools_provider"],
                values["tools_model"],
                values["speech_provider"],
                values["speech_model"],
                values["agent_provider"],
                values["agent_model"],
                now,
            ),
        )
        row = c.execute(
            "SELECT * FROM user_ai_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row)


def get_provider_credential(user_id: str, provider: str) -> str | None:
    with _conn() as c:
        row = c.execute(
            """SELECT encrypted_api_key FROM provider_credentials
               WHERE user_id = ? AND provider = ?""",
            (user_id, provider),
        ).fetchone()
        return str(row["encrypted_api_key"]) if row else None


def set_provider_credential(
    user_id: str, provider: str, encrypted_api_key: str
) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO provider_credentials
               (user_id, provider, encrypted_api_key, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, provider) DO UPDATE SET
                 encrypted_api_key = excluded.encrypted_api_key,
                 updated_at = excluded.updated_at""",
            (user_id, provider, encrypted_api_key, time.time()),
        )


def delete_provider_credential(user_id: str, provider: str) -> bool:
    with _conn() as c:
        cursor = c.execute(
            "DELETE FROM provider_credentials WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        )
        return cursor.rowcount == 1


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


# ---------- Nodos ejecutores ----------


class NodeNameTaken(Exception):
    """Ya hay un nodo activo con ese nombre para el mismo usuario."""


def _node(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    node = dict(row)
    node["capacidades"] = json.loads(node.get("capacidades") or "[]")
    return node


def _node_order(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    order = dict(row)
    order["arguments"] = json.loads(order.get("arguments") or "{}")
    resultado = order.get("resultado")
    order["resultado"] = json.loads(resultado) if resultado else None
    return order


def create_node(
    user_id: str,
    nombre: str,
    plataforma: str,
    token_hash: str,
    node_id: str | None = None,
) -> dict:
    """Registra un nodo nuevo. El token en claro nunca llega hasta aquí."""
    node_id = node_id or str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        try:
            c.execute(
                """INSERT INTO nodes
                   (id, user_id, nombre, plataforma, token_hash, estado,
                    capacidades, last_seen, created_at)
                   VALUES (?, ?, ?, ?, ?, 'activo', '[]', NULL, ?)""",
                (node_id, user_id, nombre, plataforma, token_hash, now),
            )
        except sqlite3.IntegrityError as error:
            raise NodeNameTaken(nombre) from error
        return _node(c.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone())


def get_node(node_id: str) -> dict | None:
    with _conn() as c:
        return _node(
            c.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        )


def get_node_for_user(node_id: str, user_id: str) -> dict | None:
    with _conn() as c:
        return _node(
            c.execute(
                "SELECT * FROM nodes WHERE id = ? AND user_id = ?",
                (node_id, user_id),
            ).fetchone()
        )


# ---------- Silencios de notificaciones ----------

# Cuántas reglas puede acumular un usuario. El tope está porque quien las
# escribe es un modelo interpretando frases habladas: un bucle raro no puede
# llenar la tabla, y con cien silencios distintos el problema ya no es el filtro.
MAX_SILENCIOS = 100


def list_mute_rules(user_id: str) -> list[dict]:
    """Los silencios de este usuario, del más reciente al más antiguo."""
    with _conn() as c:
        filas = c.execute(
            """SELECT id, app, patron, creado FROM avisos_silenciados
               WHERE user_id = ? ORDER BY creado DESC""",
            (user_id,),
        ).fetchall()
    return [dict(fila) for fila in filas]


def add_mute_rule(user_id: str, app: str, patron: str) -> dict | None:
    """Guarda un silencio. Devuelve None si no dice nada o si ya estaba.

    Una regla sin aplicación ni patrón no se guarda: no callaría nada y solo
    serviría para que el usuario creyera que sí.
    """
    app, patron = (app or "").strip(), (patron or "").strip()
    if not app and not patron:
        return None

    with _conn() as c:
        ya = c.execute(
            """SELECT id FROM avisos_silenciados
               WHERE user_id = ? AND app = ? AND patron = ?""",
            (user_id, app, patron),
        ).fetchone()
        if ya:
            return None
        cuantas = c.execute(
            "SELECT COUNT(*) FROM avisos_silenciados WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        if cuantas >= MAX_SILENCIOS:
            return None

        regla = {
            "id": str(uuid.uuid4()),
            "app": app,
            "patron": patron,
            "creado": time.time(),
        }
        c.execute(
            """INSERT INTO avisos_silenciados (id, user_id, app, patron, creado)
               VALUES (?, ?, ?, ?, ?)""",
            (regla["id"], user_id, app, patron, regla["creado"]),
        )
    return regla


# ---------- Permisos para actuar sobre un aviso ----------

# Mismo motivo que el tope de silencios: quien los escribe es un modelo, y cien
# permisos distintos ya no son un permiso, son una barra libre sin repasar.
MAX_PERMISOS = 100


def list_notification_permissions(user_id: str) -> list[dict]:
    """Lo que el usuario ya decidió, permitido o no, de lo más reciente atrás."""
    with _conn() as c:
        filas = c.execute(
            """SELECT id, app, accion, permitido, creado FROM avisos_permisos
               WHERE user_id = ? ORDER BY creado DESC""",
            (user_id,),
        ).fetchall()
    return [{**dict(fila), "permitido": bool(fila["permitido"])} for fila in filas]


def set_notification_permission(
    user_id: str, app: str, accion: str, permitido: bool
) -> dict | None:
    """Guarda la respuesta del usuario. Devuelve None si no dice qué acción.

    Sobreescribe la decisión anterior sobre la misma acción en vez de acumular
    otra fila: si dijo que sí y ahora dice que no, lo que vale es lo último, y
    dos filas contradictorias solo servirían para que Vibi eligiera la que le
    conviniera.
    """
    app, accion = (app or "").strip(), " ".join((accion or "").split())
    if not accion:
        return None

    with _conn() as c:
        ya = c.execute(
            """SELECT id FROM avisos_permisos
               WHERE user_id = ? AND app = ? AND accion = ?""",
            (user_id, app, accion),
        ).fetchone()
        if ya:
            c.execute(
                "UPDATE avisos_permisos SET permitido = ?, creado = ? WHERE id = ?",
                (int(permitido), time.time(), ya["id"]),
            )
            return {
                "id": ya["id"],
                "app": app,
                "accion": accion,
                "permitido": permitido,
            }
        cuantos = c.execute(
            "SELECT COUNT(*) FROM avisos_permisos WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        if cuantos >= MAX_PERMISOS:
            return None

        permiso = {
            "id": str(uuid.uuid4()),
            "app": app,
            "accion": accion,
            "permitido": permitido,
        }
        c.execute(
            """INSERT INTO avisos_permisos (id, user_id, app, accion, permitido, creado)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (permiso["id"], user_id, app, accion, int(permitido), time.time()),
        )
    return permiso


def delete_notification_permission(permiso_id: str, user_id: str) -> bool:
    """Retira una decisión ya tomada, para que vuelva a preguntarse."""
    with _conn() as c:
        cursor = c.execute(
            "DELETE FROM avisos_permisos WHERE id = ? AND user_id = ?",
            (permiso_id, user_id),
        )
    return cursor.rowcount > 0


def list_nodes(user_id: str, include_revoked: bool = False) -> list[dict]:
    query = "SELECT * FROM nodes WHERE user_id = ?"
    if not include_revoked:
        query += " AND estado = 'activo'"
    query += " ORDER BY nombre COLLATE NOCASE"
    with _conn() as c:
        return [_node(row) for row in c.execute(query, (user_id,)).fetchall()]


def revoke_node(node_id: str, user_id: str) -> dict | None:
    """Corta un nodo sin borrar su historial de órdenes."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM nodes WHERE id = ? AND user_id = ?", (node_id, user_id)
        ).fetchone()
        if not row:
            return None
        c.execute("UPDATE nodes SET estado = 'revocado' WHERE id = ?", (node_id,))
        c.execute(
            """UPDATE node_orders SET estado = 'caducada', completed_at = ?
               WHERE node_id = ? AND estado IN ('pendiente', 'entregada')""",
            (time.time(), node_id),
        )
        return _node(
            c.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        )


def touch_node(node_id: str, capacidades: list[str] | None = None) -> None:
    with _conn() as c:
        if capacidades is None:
            c.execute(
                "UPDATE nodes SET last_seen = ? WHERE id = ?",
                (time.time(), node_id),
            )
            return
        c.execute(
            "UPDATE nodes SET last_seen = ?, capacidades = ? WHERE id = ?",
            (time.time(), json.dumps(capacidades, ensure_ascii=False), node_id),
        )


def create_node_order(
    node_id: str,
    user_id: str,
    capability: str,
    arguments: dict,
    ttl_seconds: float,
    aprobacion: str = "no_requiere",
    riesgo: str = "bajo",
    motivo_aprobacion: str | None = None,
    queue_on_reconnect: bool = True,
) -> dict:
    order_id = str(uuid.uuid4())
    now = time.time()
    initial_state = "pendiente" if queue_on_reconnect else "entregada"
    delivered_at = None if queue_on_reconnect else now
    with _conn() as c:
        c.execute(
            """INSERT INTO node_orders
               (id, node_id, user_id, capability, arguments, estado,
                expires_at, created_at, delivered_at, aprobacion, riesgo,
                motivo_aprobacion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                node_id,
                user_id,
                capability,
                json.dumps(arguments, ensure_ascii=False),
                initial_state,
                now + ttl_seconds,
                now,
                delivered_at,
                aprobacion,
                riesgo,
                motivo_aprobacion,
            ),
        )
        return _node_order(
            c.execute("SELECT * FROM node_orders WHERE id = ?", (order_id,)).fetchone()
        )


def cancel_node_order(order_id: str, user_id: str, reason: str) -> dict | None:
    """Cierra una orden que no debe sobrevivir a una desconexión."""
    with _conn() as c:
        cursor = c.execute(
            """UPDATE node_orders
               SET estado = 'error', resultado = ?, completed_at = ?
               WHERE id = ? AND user_id = ?
                 AND estado IN ('pendiente', 'entregada')""",
            (
                json.dumps({"error": reason}, ensure_ascii=False),
                time.time(),
                order_id,
                user_id,
            ),
        )
        if not cursor.rowcount:
            return None
        return _node_order(
            c.execute("SELECT * FROM node_orders WHERE id = ?", (order_id,)).fetchone()
        )


def get_node_order(order_id: str) -> dict | None:
    with _conn() as c:
        return _node_order(
            c.execute(
                "SELECT * FROM node_orders WHERE id = ?", (order_id,)
            ).fetchone()
        )


def claim_node_orders(node_id: str) -> list[dict]:
    """Marca como entregadas las órdenes vivas de un nodo que acaba de conectar."""
    now = time.time()
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM node_orders
               WHERE node_id = ? AND estado = 'pendiente' AND expires_at > ?
                 AND aprobacion IN ('no_requiere', 'aprobada')
               ORDER BY created_at""",
            (node_id, now),
        ).fetchall()
        if rows:
            c.executemany(
                """UPDATE node_orders SET estado = 'entregada', delivered_at = ?
                   WHERE id = ?""",
                [(now, row["id"]) for row in rows],
            )
        return [_node_order(row) for row in rows]


def mark_node_order_delivered(order_id: str) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE node_orders SET estado = 'entregada', delivered_at = ?
               WHERE id = ? AND estado = 'pendiente'""",
            (time.time(), order_id),
        )


def approve_node_order(order_id: str, user_id: str) -> dict | None:
    """Da el visto bueno humano. Solo el dueño de la orden puede hacerlo."""
    with _conn() as c:
        cursor = c.execute(
            """UPDATE node_orders SET aprobacion = 'aprobada'
               WHERE id = ? AND user_id = ? AND aprobacion = 'pendiente'
                 AND estado = 'pendiente' AND expires_at > ?""",
            (order_id, user_id, time.time()),
        )
        if not cursor.rowcount:
            return None
        return _node_order(
            c.execute("SELECT * FROM node_orders WHERE id = ?", (order_id,)).fetchone()
        )


def reject_node_order(order_id: str, user_id: str) -> dict | None:
    """Cierra la orden sin ejecutarla. Un rechazo no se reintenta jamás."""
    with _conn() as c:
        cursor = c.execute(
            """UPDATE node_orders
               SET aprobacion = 'rechazada', estado = 'error',
                   resultado = ?, completed_at = ?
               WHERE id = ? AND user_id = ? AND aprobacion = 'pendiente'
                 AND estado = 'pendiente'""",
            (
                json.dumps({"error": "Rechazada por el usuario"}, ensure_ascii=False),
                time.time(),
                order_id,
                user_id,
            ),
        )
        if not cursor.rowcount:
            return None
        return _node_order(
            c.execute("SELECT * FROM node_orders WHERE id = ?", (order_id,)).fetchone()
        )


def list_pending_node_approvals(user_id: str) -> list[dict]:
    """Lo que espera tu decisión ahora mismo, sin lo ya caducado."""
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM node_orders
               WHERE user_id = ? AND aprobacion = 'pendiente'
                 AND estado = 'pendiente' AND expires_at > ?
               ORDER BY created_at DESC""",
            (user_id, time.time()),
        ).fetchall()
        return [_node_order(row) for row in rows]


def set_node_shell(node_id: str, user_id: str, habilitado: bool) -> dict | None:
    with _conn() as c:
        cursor = c.execute(
            "UPDATE nodes SET shell_habilitado = ? WHERE id = ? AND user_id = ?",
            (1 if habilitado else 0, node_id, user_id),
        )
        if not cursor.rowcount:
            return None
        return _node(
            c.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        )


def set_all_nodes_shell(user_id: str, habilitado: bool) -> int:
    """Kill switch: apaga (o reabre) la ejecución en todas tus máquinas.

    Cancela además lo que estuviera esperando tu visto bueno: si estás bajando
    la persiana, lo que hay en la cola es justo lo que no quieres que corra.
    """
    with _conn() as c:
        cursor = c.execute(
            "UPDATE nodes SET shell_habilitado = ? WHERE user_id = ? AND estado = 'activo'",
            (1 if habilitado else 0, user_id),
        )
        if not habilitado:
            c.execute(
                """UPDATE node_orders
                   SET aprobacion = 'rechazada', estado = 'error',
                       resultado = ?, completed_at = ?
                   WHERE user_id = ? AND aprobacion = 'pendiente'
                     AND estado = 'pendiente'""",
                (
                    json.dumps(
                        {"error": "Cancelada al apagar la ejecución remota"},
                        ensure_ascii=False,
                    ),
                    time.time(),
                    user_id,
                ),
            )
        return cursor.rowcount


def finish_node_order(
    order_id: str, node_id: str, estado: str, resultado: dict | None
) -> dict | None:
    """Cierra una orden. Solo el nodo destinatario puede hacerlo."""
    if estado not in ("ok", "error"):
        raise ValueError(f"Estado de cierre no soportado: {estado}")
    with _conn() as c:
        cursor = c.execute(
            """UPDATE node_orders
               SET estado = ?, resultado = ?, completed_at = ?
               WHERE id = ? AND node_id = ? AND estado IN ('pendiente', 'entregada')""",
            (
                estado,
                json.dumps(resultado, ensure_ascii=False) if resultado is not None else None,
                time.time(),
                order_id,
                node_id,
            ),
        )
        if not cursor.rowcount:
            return None
        return _node_order(
            c.execute("SELECT * FROM node_orders WHERE id = ?", (order_id,)).fetchone()
        )


def expire_node_orders() -> list[dict]:
    """Caduca las órdenes que nadie recogió a tiempo."""
    now = time.time()
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM node_orders
               WHERE estado IN ('pendiente', 'entregada') AND expires_at <= ?""",
            (now,),
        ).fetchall()
        if rows:
            c.executemany(
                """UPDATE node_orders SET estado = 'caducada', completed_at = ?
                   WHERE id = ?""",
                [(now, row["id"]) for row in rows],
            )
        return [_node_order(row) for row in rows]


def list_node_orders(
    node_id: str, user_id: str, limit: int = 20
) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM node_orders
               WHERE node_id = ? AND user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (node_id, user_id, limit),
        ).fetchall()
        return [_node_order(row) for row in rows]


# ---------- Transferencias ----------

def _transfer(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def create_transfer(
    user_id: str,
    nombre: str,
    estado: str,
    ttl_seconds: float,
    *,
    origen_node_id: str | None = None,
    destino_node_id: str | None = None,
    destino_canal: str | None = None,
    file_id: str | None = None,
    ruta_origen: str | None = None,
    bytes_esperados: int | None = None,
    bytes_recibidos: int = 0,
) -> dict:
    transfer_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO transfers
               (id, user_id, origen_node_id, destino_node_id, destino_canal,
                file_id, nombre, ruta_origen, bytes_esperados, bytes_recibidos,
                estado, expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                transfer_id,
                user_id,
                origen_node_id,
                destino_node_id,
                destino_canal,
                file_id,
                nombre,
                ruta_origen,
                bytes_esperados,
                bytes_recibidos,
                estado,
                now + ttl_seconds,
                now,
                now,
            ),
        )
        return _transfer(
            c.execute(
                "SELECT * FROM transfers WHERE id = ?", (transfer_id,)
            ).fetchone()
        )


def get_transfer(transfer_id: str) -> dict | None:
    with _conn() as c:
        return _transfer(
            c.execute(
                "SELECT * FROM transfers WHERE id = ?", (transfer_id,)
            ).fetchone()
        )


def get_transfer_for_user(transfer_id: str, user_id: str) -> dict | None:
    with _conn() as c:
        return _transfer(
            c.execute(
                "SELECT * FROM transfers WHERE id = ? AND user_id = ?",
                (transfer_id, user_id),
            ).fetchone()
        )


def update_transfer(transfer_id: str, **campos) -> dict | None:
    """Actualiza una transferencia. `updated_at` se pone solo."""
    permitidas = {
        "estado",
        "file_id",
        "nombre",
        "bytes_recibidos",
        "bytes_esperados",
        "destino_node_id",
        "destino_canal",
        "error",
    }
    cambios = {k: v for k, v in campos.items() if k in permitidas}
    if not cambios:
        return get_transfer(transfer_id)
    asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
    with _conn() as c:
        c.execute(
            f"UPDATE transfers SET {asignaciones}, updated_at = ? WHERE id = ?",
            (*cambios.values(), time.time(), transfer_id),
        )
        return _transfer(
            c.execute(
                "SELECT * FROM transfers WHERE id = ?", (transfer_id,)
            ).fetchone()
        )


def claim_transfer_upload(transfer_id: str, node_id: str) -> dict | None:
    """Reserva la subida para el nodo de origen. Solo la gana uno.

    El paso a `entregando` es la marca de que ya hay una subida en curso: una
    segunda petición para la misma transferencia no encuentra la fila y se
    rechaza, en vez de pisar el archivo a medio escribir.
    """
    with _conn() as c:
        cursor = c.execute(
            """UPDATE transfers SET estado = 'entregando', updated_at = ?
               WHERE id = ? AND origen_node_id = ? AND estado = 'esperando_origen'""",
            (time.time(), transfer_id, node_id),
        )
        if cursor.rowcount == 0:
            return None
        return _transfer(
            c.execute(
                "SELECT * FROM transfers WHERE id = ?", (transfer_id,)
            ).fetchone()
        )


def close_transfer(transfer_id: str, estado: str, error: str | None = None) -> dict | None:
    """Cierra una entrega. Devuelve la fila solo si este cierre fue el que valió.

    Hay dos sitios que pueden enterarse de que la entrega terminó —la llamada
    que estaba esperando respuesta y el resultado que llega suelto cuando la
    máquina se enciende— y no hay forma de saber cuál llegará antes. Cerrar
    aquí, condicionado al estado, deja que gane uno solo: el otro recibe None y
    no vuelve a anunciar lo mismo.
    """
    if estado not in ("entregado", "error"):
        raise ValueError(f"Cierre no soportado: {estado}")
    with _conn() as c:
        cursor = c.execute(
            """UPDATE transfers SET estado = ?, error = ?, updated_at = ?
               WHERE id = ? AND estado IN ('en_servidor', 'entregando')""",
            (estado, error, time.time(), transfer_id),
        )
        if not cursor.rowcount:
            return None
        return _transfer(
            c.execute(
                "SELECT * FROM transfers WHERE id = ?", (transfer_id,)
            ).fetchone()
        )


def expire_transfers() -> list[dict]:
    """Caduca las transferencias que nadie completó a tiempo.

    El archivo ya materializado no se toca: a partir de `en_servidor` es un
    archivo del usuario como cualquier otro, y lo que caduca es la entrega.
    """
    now = time.time()
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM transfers
               WHERE estado IN ('esperando_origen', 'en_servidor', 'entregando')
                 AND expires_at <= ?""",
            (now,),
        ).fetchall()
        if rows:
            c.executemany(
                """UPDATE transfers SET estado = 'caducada', updated_at = ?
                   WHERE id = ?""",
                [(now, row["id"]) for row in rows],
            )
        return [_transfer(row) for row in rows]


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


# ---------- Proyectos ----------

def create_project(
    user_id: str,
    nombre: str,
    slug: str,
    descripcion: str = "",
) -> dict | None:
    """Registra un proyecto. Devuelve None si el usuario ya tiene ese slug."""
    project_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        try:
            c.execute(
                """INSERT INTO projects
                   (id, user_id, nombre, slug, descripcion, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, user_id, nombre, slug, descripcion, now, now),
            )
        except sqlite3.IntegrityError:
            return None
        row = c.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) | {"archivos": 0, "conversaciones": 0}


# Un proyecto se lee siempre con lo que cuelga de él: leerlo sin los contadores
# devolvía una ficha que decía «0 archivos» sobre un proyecto que tenía varios,
# según por qué ruta se hubiera pedido.
_PROJECT_SELECT = """
    SELECT p.*,
           (SELECT COUNT(*) FROM files AS f
             WHERE f.project_id = p.id AND f.deleted_at IS NULL) AS archivos,
           (SELECT COUNT(*) FROM conversations AS v
             WHERE v.project_id = p.id) AS conversaciones
      FROM projects AS p
"""


def get_project(project_id: str, user_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            f"{_PROJECT_SELECT} WHERE p.id = ? AND p.user_id = ?",
            (project_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def get_project_by_slug(user_id: str, slug: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            f"{_PROJECT_SELECT} WHERE p.user_id = ? AND p.slug = ?",
            (user_id, slug),
        ).fetchone()
        return dict(row) if row else None


def list_projects(user_id: str) -> list[dict]:
    """Los proyectos del usuario con lo que cuelga de cada uno."""
    with _conn() as c:
        rows = c.execute(
            f"""{_PROJECT_SELECT}
                WHERE p.user_id = ?
                ORDER BY p.updated_at DESC, p.nombre COLLATE NOCASE""",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_project(
    project_id: str,
    user_id: str,
    nombre: str | None = None,
    descripcion: str | None = None,
) -> dict | None:
    """Cambia lo editable de un proyecto sin tocar su slug ni su carpeta."""
    campos: list[str] = []
    valores: list[object] = []
    if nombre is not None:
        campos.append("nombre = ?")
        valores.append(nombre)
    if descripcion is not None:
        campos.append("descripcion = ?")
        valores.append(descripcion)
    if not campos:
        return get_project(project_id, user_id)
    campos.append("updated_at = ?")
    valores.extend([time.time(), project_id, user_id])
    with _conn() as c:
        cursor = c.execute(
            f"UPDATE projects SET {', '.join(campos)} WHERE id = ? AND user_id = ?",
            valores,
        )
        if cursor.rowcount != 1:
            return None
        row = c.execute(
            f"{_PROJECT_SELECT} WHERE p.id = ?", (project_id,)
        ).fetchone()
        return dict(row)


def touch_project(project_id: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (time.time(), project_id),
        )


def delete_project_record(project_id: str, user_id: str) -> bool:
    """Borra el proyecto soltando antes lo que lo referencia.

    Los archivos y las conversaciones sobreviven al proyecto: quedan sueltos
    en el espacio del usuario en vez de desaparecer con él. Borrar los blobs
    es decisión de quien llama, no de la base.
    """
    with _conn() as c:
        c.execute(
            "UPDATE files SET project_id = NULL WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        c.execute(
            """UPDATE conversations SET project_id = NULL
               WHERE project_id = ? AND user_id = ?""",
            (project_id, user_id),
        )
        cursor = c.execute(
            "DELETE FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        )
        return cursor.rowcount == 1


def list_project_files(project_id: str, user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM files
               WHERE project_id = ? AND user_id = ? AND deleted_at IS NULL
               ORDER BY created_at DESC, id""",
            (project_id, user_id),
        ).fetchall()
        return [dict(row) for row in rows]


def set_file_project(
    file_id: str, user_id: str, project_id: str | None
) -> dict | None:
    """Mueve un archivo dentro o fuera de un proyecto (solo el metadato)."""
    with _conn() as c:
        cursor = c.execute(
            """UPDATE files SET project_id = ?, modified_at = ?
               WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
            (project_id, time.time(), file_id, user_id),
        )
        if cursor.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return dict(row)


# ---------- Archivos personales ----------

def create_managed_file(
    user_id: str,
    name: str,
    storage_key: str,
    media_type: str | None,
    size_bytes: int,
    sha256: str,
    project_id: str | None = None,
) -> dict:
    file_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO files
               (id, user_id, project_id, source, name, storage_key, media_type,
                size_bytes, sha256, modified_at, created_at)
               VALUES (?, ?, ?, 'managed', ?, ?, ?, ?, ?, ?, ?)""",
            (
                file_id, user_id, project_id, name, storage_key, media_type,
                size_bytes, sha256, now, now,
            ),
        )
        return dict(c.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone())


def create_managed_file_within_quota(
    user_id: str,
    name: str,
    storage_key: str,
    media_type: str | None,
    size_bytes: int,
    sha256: str,
    quota_bytes: int,
    project_id: str | None = None,
) -> dict | None:
    """Reserva cuota e inserta el metadato bajo un único bloqueo de escritura."""
    file_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        usage = c.execute(
            """SELECT COALESCE(SUM(size_bytes), 0) AS total FROM files
               WHERE user_id = ? AND source = 'managed' AND deleted_at IS NULL""",
            (user_id,),
        ).fetchone()
        if int(usage["total"]) + size_bytes > quota_bytes:
            return None
        c.execute(
            """INSERT INTO files
               (id, user_id, project_id, source, name, storage_key, media_type,
                size_bytes, sha256, modified_at, created_at)
               VALUES (?, ?, ?, 'managed', ?, ?, ?, ?, ?, ?, ?)""",
            (
                file_id, user_id, project_id, name, storage_key, media_type,
                size_bytes, sha256, now, now,
            ),
        )
        return dict(c.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone())


def delete_managed_file_record(file_id: str, user_id: str) -> None:
    """Retira una reserva cuyo blob no pudo publicarse."""
    with _conn() as c:
        c.execute(
            "DELETE FROM files WHERE id = ? AND user_id = ? AND source = 'managed'",
            (file_id, user_id),
        )


def list_managed_files(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM files
               WHERE user_id = ? AND source = 'managed' AND deleted_at IS NULL
               ORDER BY created_at, id""",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_managed_file_location(
    file_id: str,
    user_id: str,
    name: str,
    storage_key: str,
) -> dict | None:
    """Confirma la ubicación legible de una subida perteneciente al usuario."""
    with _conn() as c:
        cursor = c.execute(
            """UPDATE files SET name = ?, storage_key = ?, modified_at = ?
               WHERE id = ? AND user_id = ? AND source = 'managed'
                 AND deleted_at IS NULL""",
            (name, storage_key, time.time(), file_id, user_id),
        )
        if cursor.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return dict(row)


def upsert_workspace_file(
    user_id: str,
    relative_path: str,
    name: str,
    size_bytes: int,
    modified_at: float,
    media_type: str | None,
) -> dict:
    now = time.time()
    with _conn() as c:
        row = c.execute(
            """SELECT id, modified_at FROM files
               WHERE user_id = ? AND source = 'workspace'
                 AND relative_path = ? AND deleted_at IS NULL""",
            (user_id, relative_path),
        ).fetchone()
        if row:
            file_id = row["id"]
            content_reset = (
                ""
                if row["modified_at"] == modified_at
                else ", content_text = NULL, content_indexed_at = NULL"
            )
            c.execute(
                f"""UPDATE files SET name = ?, size_bytes = ?, modified_at = ?,
                    media_type = ?{content_reset} WHERE id = ?""",
                (name, size_bytes, modified_at, media_type, file_id),
            )
        else:
            file_id = str(uuid.uuid4())
            c.execute(
                """INSERT INTO files
                   (id, user_id, source, name, relative_path, media_type,
                    size_bytes, modified_at, created_at)
                   VALUES (?, ?, 'workspace', ?, ?, ?, ?, ?, ?)""",
                (
                    file_id, user_id, name, relative_path, media_type,
                    size_bytes, modified_at, now,
                ),
            )
        return dict(c.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone())


def set_file_content_index(file_id: str, user_id: str, content_text: str) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE files SET content_text = ?, content_indexed_at = ?
               WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
            (content_text, time.time(), file_id, user_id),
        )


def get_file_for_user(file_id: str, user_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            """SELECT * FROM files
               WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
            (file_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def list_files(user_id: str, limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM files
               WHERE user_id = ? AND deleted_at IS NULL
               ORDER BY modified_at DESC, name COLLATE NOCASE
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def managed_usage(user_id: str) -> int:
    with _conn() as c:
        row = c.execute(
            """SELECT COALESCE(SUM(size_bytes), 0) AS total FROM files
               WHERE user_id = ? AND source = 'managed' AND deleted_at IS NULL""",
            (user_id,),
        ).fetchone()
        return int(row["total"])


def soft_delete_file(file_id: str, user_id: str) -> dict | None:
    now = time.time()
    with _conn() as c:
        cursor = c.execute(
            """UPDATE files SET deleted_at = ?
               WHERE id = ? AND user_id = ? AND source = 'managed'
                 AND deleted_at IS NULL""",
            (now, file_id, user_id),
        )
        if cursor.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return dict(row)


# ---------- Herramientas ----------

def create_tool(
    scope: str,
    owner_user_id: str | None,
    name: str,
    description: str,
    primitive_id: str,
    bound_arguments: dict,
    source: str = "human",
) -> dict:
    tool_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO tools
               (id, scope, owner_user_id, name, description, primitive_id,
                bound_arguments, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tool_id, scope, owner_user_id, name, description, primitive_id,
                json.dumps(bound_arguments, ensure_ascii=False), source, now, now,
            ),
        )
        return dict(c.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone())


def list_tools_for_user(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM tools
               WHERE scope = 'lab' OR owner_user_id = ?
               ORDER BY scope, name COLLATE NOCASE""",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_tool_for_user(tool_id: str, user_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            """SELECT * FROM tools
               WHERE id = ? AND (scope = 'lab' OR owner_user_id = ?)""",
            (tool_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def update_tool(
    tool_id: str,
    scope: str,
    owner_user_id: str | None,
    name: str,
    description: str,
    primitive_id: str,
    bound_arguments: dict,
) -> dict | None:
    with _conn() as c:
        cursor = c.execute(
            """UPDATE tools
               SET scope = ?, owner_user_id = ?, name = ?, description = ?,
                   primitive_id = ?, bound_arguments = ?, updated_at = ?
               WHERE id = ?""",
            (
                scope,
                owner_user_id,
                name,
                description,
                primitive_id,
                json.dumps(bound_arguments, ensure_ascii=False),
                time.time(),
                tool_id,
            ),
        )
        if cursor.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
        return dict(row)


def set_tool_enabled(tool_id: str, user_id: str, enabled: bool) -> dict | None:
    with _conn() as c:
        cursor = c.execute(
            """UPDATE tools SET enabled = ?, updated_at = ?
               WHERE id = ? AND owner_user_id = ?""",
            (int(enabled), time.time(), tool_id, user_id),
        )
        if cursor.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
        return dict(row)


def set_tool_enabled_by_id(tool_id: str, enabled: bool) -> dict | None:
    with _conn() as c:
        cursor = c.execute(
            "UPDATE tools SET enabled = ?, updated_at = ? WHERE id = ?",
            (int(enabled), time.time(), tool_id),
        )
        if cursor.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
        return dict(row)


def start_tool_invocation(tool_id: str, actor_user_id: str) -> str:
    invocation_id = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            """INSERT INTO tool_invocations
               (id, tool_id, actor_user_id, status, requested_at)
               VALUES (?, ?, ?, 'running', ?)""",
            (invocation_id, tool_id, actor_user_id, time.time()),
        )
    return invocation_id


def finish_tool_invocation(
    invocation_id: str,
    status: str,
    started_at: float,
    error_code: str | None = None,
) -> None:
    now = time.time()
    with _conn() as c:
        c.execute(
            """UPDATE tool_invocations
               SET status = ?, error_code = ?, completed_at = ?, duration_ms = ?
               WHERE id = ?""",
            (status, error_code, now, int((now - started_at) * 1000), invocation_id),
        )


def list_tool_invocations(
    tool_id: str, actor_user_id: str, limit: int = 25
) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT id, tool_id, status, error_code, requested_at,
                      completed_at, duration_ms
               FROM tool_invocations
               WHERE tool_id = ? AND actor_user_id = ?
               ORDER BY requested_at DESC LIMIT ?""",
            (tool_id, actor_user_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def tool_usage_for_user(actor_user_id: str) -> dict[str, dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT tool_id,
                      COUNT(*) AS total,
                      SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
                      SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                      SUM(CASE WHEN status = 'denied' THEN 1 ELSE 0 END) AS denied,
                      MAX(requested_at) AS last_used_at,
                      CAST(ROUND(AVG(duration_ms)) AS INTEGER) AS average_duration_ms
               FROM tool_invocations
               WHERE actor_user_id = ?
               GROUP BY tool_id""",
            (actor_user_id,),
        ).fetchall()
    return {row["tool_id"]: dict(row) for row in rows}


# ---------- Herramientas de guion (forja) ----------

def create_tool_script(
    tool_id: str,
    owner_user_id: str,
    slug: str,
    name: str,
    description: str,
    parametros: list[dict],
    codigo: str,
    peticion: str,
    modelo: str,
    comprobacion: dict,
    enabled: bool,
) -> dict:
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO tool_scripts
               (id, owner_user_id, slug, name, description, parametros, codigo,
                peticion, modelo, comprobacion, enabled, version,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                tool_id, owner_user_id, slug, name, description,
                json.dumps(parametros, ensure_ascii=False), codigo, peticion,
                modelo, json.dumps(comprobacion, ensure_ascii=False, default=str),
                int(enabled), now, now,
            ),
        )
        return dict(
            c.execute(
                "SELECT * FROM tool_scripts WHERE id = ?", (tool_id,)
            ).fetchone()
        )


def update_tool_script(
    tool_id: str,
    owner_user_id: str,
    name: str,
    description: str,
    parametros: list[dict],
    codigo: str,
    peticion: str,
    modelo: str,
    comprobacion: dict,
    enabled: bool,
) -> dict | None:
    """Rehace el guion conservando su identidad y subiendo la versión.

    Filtra por dueño como sus tres hermanas: hoy quien llama ya ha cargado la
    fila con `get_tool_script`, pero era la única de las cuatro que dependía de
    que el de arriba se acordara.
    """
    with _conn() as c:
        c.execute(
            """UPDATE tool_scripts
               SET name = ?, description = ?, parametros = ?, codigo = ?,
                   peticion = ?, modelo = ?, comprobacion = ?, enabled = ?,
                   version = version + 1, updated_at = ?
               WHERE id = ? AND owner_user_id = ?""",
            (
                name, description,
                json.dumps(parametros, ensure_ascii=False), codigo, peticion,
                modelo, json.dumps(comprobacion, ensure_ascii=False, default=str),
                int(enabled), time.time(), tool_id, owner_user_id,
            ),
        )
        row = c.execute(
            "SELECT * FROM tool_scripts WHERE id = ? AND owner_user_id = ?",
            (tool_id, owner_user_id),
        ).fetchone()
        return dict(row) if row else None


def list_tool_scripts(owner_user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM tool_scripts
               WHERE owner_user_id = ?
               ORDER BY name COLLATE NOCASE""",
            (owner_user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_tool_script(tool_id: str, owner_user_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM tool_scripts WHERE id = ? AND owner_user_id = ?",
            (tool_id, owner_user_id),
        ).fetchone()
        return dict(row) if row else None


def set_tool_script_enabled(
    tool_id: str, owner_user_id: str, enabled: bool
) -> dict | None:
    with _conn() as c:
        c.execute(
            """UPDATE tool_scripts SET enabled = ?, updated_at = ?
               WHERE id = ? AND owner_user_id = ?""",
            (int(enabled), time.time(), tool_id, owner_user_id),
        )
        row = c.execute(
            "SELECT * FROM tool_scripts WHERE id = ? AND owner_user_id = ?",
            (tool_id, owner_user_id),
        ).fetchone()
        return dict(row) if row else None


# ---------- Skills ----------

def _skill_snapshot(row: dict) -> dict:
    return {
        "slug": row["slug"],
        "name": row["name"],
        "description": row["description"],
        "instructions": row["instructions"],
        "examples": json.loads(row["examples"]),
        "tool_ids": json.loads(row["tool_ids"]),
        "scope": row["scope"],
    }


def _insert_skill_version(c: sqlite3.Connection, row: dict) -> None:
    c.execute(
        """INSERT INTO skill_versions (skill_id, version, snapshot, created_at)
           VALUES (?, ?, ?, ?)""",
        (
            row["id"],
            row["version"],
            json.dumps(_skill_snapshot(row), ensure_ascii=False),
            row["updated_at"],
        ),
    )


def create_skill_record(
    scope: str,
    owner_user_id: str | None,
    slug: str,
    name: str,
    description: str,
    instructions: str,
    examples: list[str],
    tool_ids: list[str],
) -> dict:
    skill_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO skills
               (id, scope, owner_user_id, slug, name, description, instructions,
                examples, tool_ids, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                skill_id,
                scope,
                owner_user_id,
                slug,
                name,
                description,
                instructions,
                json.dumps(examples, ensure_ascii=False),
                json.dumps(tool_ids, ensure_ascii=False),
                now,
                now,
            ),
        )
        row = dict(c.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone())
        _insert_skill_version(c, row)
        return row


def update_skill_record(
    skill_id: str,
    scope: str,
    owner_user_id: str | None,
    slug: str,
    name: str,
    description: str,
    instructions: str,
    examples: list[str],
    tool_ids: list[str],
    enabled: bool,
) -> dict | None:
    now = time.time()
    with _conn() as c:
        cursor = c.execute(
            """UPDATE skills
               SET scope = ?, owner_user_id = ?, slug = ?, name = ?,
                   description = ?, instructions = ?, examples = ?, tool_ids = ?,
                   enabled = ?,
                   version = version + 1, updated_at = ?
               WHERE id = ?""",
            (
                scope,
                owner_user_id,
                slug,
                name,
                description,
                instructions,
                json.dumps(examples, ensure_ascii=False),
                json.dumps(tool_ids, ensure_ascii=False),
                int(enabled),
                now,
                skill_id,
            ),
        )
        if cursor.rowcount != 1:
            return None
        row = dict(c.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone())
        _insert_skill_version(c, row)
        return row


def get_skill(skill_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        return dict(row) if row else None


def get_skill_by_slug(
    scope: str, owner_user_id: str | None, slug: str
) -> dict | None:
    with _conn() as c:
        if scope == "lab":
            row = c.execute(
                "SELECT * FROM skills WHERE scope = 'lab' AND slug = ?", (slug,)
            ).fetchone()
        else:
            row = c.execute(
                """SELECT * FROM skills
                   WHERE scope = 'personal' AND owner_user_id = ? AND slug = ?""",
                (owner_user_id, slug),
            ).fetchone()
        return dict(row) if row else None


def get_active_skill_by_slug(user_id: str, slug: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            """SELECT * FROM skills
               WHERE enabled = 1 AND slug = ?
                 AND (owner_user_id = ? OR scope = 'lab')
               ORDER BY CASE scope WHEN 'personal' THEN 0 ELSE 1 END
               LIMIT 1""",
            (slug, user_id),
        ).fetchone()
        return dict(row) if row else None


def list_skills_for_user(user_id: str, include_inactive_lab: bool = False) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM skills
               WHERE owner_user_id = ?
                  OR (scope = 'lab' AND (enabled = 1 OR ? = 1))
               ORDER BY enabled DESC, updated_at DESC, name COLLATE NOCASE""",
            (user_id, int(include_inactive_lab)),
        ).fetchall()
        return [dict(row) for row in rows]


def list_skill_versions(skill_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT version, snapshot, created_at FROM skill_versions
               WHERE skill_id = ? ORDER BY version DESC""",
            (skill_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def set_skill_enabled_record(skill_id: str, enabled: bool) -> dict | None:
    with _conn() as c:
        cursor = c.execute(
            "UPDATE skills SET enabled = ?, updated_at = ? WHERE id = ?",
            (int(enabled), time.time(), skill_id),
        )
        if cursor.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        return dict(row)


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


def reset_active_conversation(
    user_id: str, expected_conversation_id: str | None = None
) -> dict | None:
    """Archiva la conversación activa si aún es la esperada y crea otra vacía."""
    conversation_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as c:
        current = c.execute(
            """SELECT id, thinking_enabled FROM conversations
               WHERE user_id = ? AND estado = 'activa'""",
            (user_id,),
        ).fetchone()
        if expected_conversation_id and (
            not current or current["id"] != expected_conversation_id
        ):
            return None
        thinking_enabled = int(current["thinking_enabled"]) if current else 0
        c.execute(
            """UPDATE conversations SET estado = 'archivada', updated_at = ?
               WHERE user_id = ? AND estado = 'activa'""",
            (now, user_id),
        )
        c.execute(
            """INSERT INTO conversations
               (id, user_id, estado, thinking_enabled, created_at, updated_at)
               VALUES (?, ?, 'activa', ?, ?, ?)""",
            (conversation_id, user_id, thinking_enabled, now, now),
        )
        row = c.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row)


def update_conversation_session(
    conversation_id: str, user_id: str, session_id: str | None
) -> bool:
    """Guarda la sesión de Claude solo en una conversación del usuario."""
    with _conn() as c:
        cursor = c.execute(
            """UPDATE conversations
               SET claude_session_id = ?, updated_at = ?
               WHERE id = ? AND user_id = ? AND estado = 'activa'""",
            (session_id, time.time(), conversation_id, user_id),
        )
        return cursor.rowcount == 1


def set_active_conversation_thinking(user_id: str, enabled: bool) -> dict:
    """Actualiza Thinking y devuelve la conversación activa resultante."""
    conversation = get_or_create_active_conversation(user_id)
    with _conn() as c:
        c.execute(
            """UPDATE conversations
               SET thinking_enabled = ?, updated_at = ?
               WHERE id = ? AND user_id = ? AND estado = 'activa'""",
            (int(enabled), time.time(), conversation["id"], user_id),
        )
        row = c.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation["id"], user_id),
        ).fetchone()
        if not row:
            raise RuntimeError("No se pudo actualizar Thinking")
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
        "thinking_enabled": bool(conversation.get("thinking_enabled")),
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


# ---------- Conversaciones guardadas ----------

def save_conversation(
    conversation_id: str,
    user_id: str,
    project_id: str | None = None,
    titulo: str | None = None,
) -> dict | None:
    """Da nombre a una conversación y la cuelga de un proyecto.

    Guardar no la cierra: se sigue hablando en ella. Lo que cambia es que deja
    de ser un hilo anónimo y pasa a estar donde se la va a buscar después.
    """
    campos = ["project_id = ?", "updated_at = ?"]
    valores: list[object] = [project_id, time.time()]
    if titulo is not None:
        campos.insert(1, "titulo = ?")
        valores.insert(1, titulo)
    valores.extend([conversation_id, user_id])
    with _conn() as c:
        cursor = c.execute(
            f"UPDATE conversations SET {', '.join(campos)} "
            "WHERE id = ? AND user_id = ?",
            valores,
        )
        if cursor.rowcount != 1:
            return None
        if project_id:
            c.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ? AND user_id = ?",
                (time.time(), project_id, user_id),
            )
        row = c.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row)


def get_conversation(conversation_id: str, user_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def _decorate_conversations(rows) -> list[dict]:
    return [dict(row) for row in rows]


def list_project_conversations(project_id: str, user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT c.*,
                      (SELECT COUNT(*) FROM messages AS m
                        WHERE m.conversation_id = c.id) AS mensajes
               FROM conversations AS c
               WHERE c.project_id = ? AND c.user_id = ?
               ORDER BY c.updated_at DESC""",
            (project_id, user_id),
        ).fetchall()
        return _decorate_conversations(rows)


def list_saved_conversations(user_id: str, limit: int = 50) -> list[dict]:
    """Las conversaciones con nombre o con proyecto, la activa incluida."""
    with _conn() as c:
        rows = c.execute(
            """SELECT c.*,
                      (SELECT COUNT(*) FROM messages AS m
                        WHERE m.conversation_id = c.id) AS mensajes
               FROM conversations AS c
               WHERE c.user_id = ?
                 AND (c.titulo IS NOT NULL OR c.project_id IS NOT NULL)
               ORDER BY c.updated_at DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return _decorate_conversations(rows)


def list_conversation_messages(
    conversation_id: str,
    user_id: str,
    limit: int = 200,
    before_id: int | None = None,
) -> list[dict] | None:
    """Mensajes de una conversación concreta del usuario, en orden cronológico."""
    params: list[object] = [conversation_id]
    before_clause = ""
    if before_id is not None:
        before_clause = "AND m.id < ?"
        params.append(before_id)
    params.append(limit)
    with _conn() as c:
        owner = c.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if not owner:
            return None
        rows = c.execute(
            f"""SELECT m.* FROM messages AS m
                WHERE m.conversation_id = ? {before_clause}
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT ?""",
            params,
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def activate_conversation(conversation_id: str, user_id: str) -> dict | None:
    """Retoma una conversación guardada archivando la que estuviera activa.

    El índice parcial de `conversations` solo admite una activa por usuario,
    así que archivar y activar tienen que ocurrir en la misma transacción.
    """
    now = time.time()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        target = c.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if not target:
            return None
        previous = c.execute(
            """SELECT id FROM conversations
               WHERE user_id = ? AND estado = 'activa'""",
            (user_id,),
        ).fetchone()
        if previous and previous["id"] == conversation_id:
            return dict(target)
        if previous:
            c.execute(
                """UPDATE conversations SET estado = 'archivada', updated_at = ?
                   WHERE id = ?""",
                (now, previous["id"]),
            )
        c.execute(
            "UPDATE conversations SET estado = 'activa', updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        row = c.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row)


# ---------- Adjuntos de mensajes ----------

def attach_files_to_message(message_id: int, file_ids: tuple[str, ...]) -> None:
    """Deja constancia de con qué archivos se envió un mensaje."""
    if not file_ids:
        return
    now = time.time()
    with _conn() as c:
        c.executemany(
            """INSERT OR IGNORE INTO message_attachments
               (message_id, file_id, created_at) VALUES (?, ?, ?)""",
            [(message_id, file_id, now) for file_id in file_ids],
        )


def attachments_for_messages(message_ids: list[int]) -> dict[int, list[dict]]:
    """Los adjuntos de una tanda de mensajes, agrupados por mensaje."""
    if not message_ids:
        return {}
    marcadores = ",".join("?" for _ in message_ids)
    with _conn() as c:
        rows = c.execute(
            f"""SELECT a.message_id, f.* FROM message_attachments AS a
                JOIN files AS f ON f.id = a.file_id
                WHERE a.message_id IN ({marcadores})
                ORDER BY a.created_at, f.name""",
            message_ids,
        ).fetchall()
    agrupados: dict[int, list[dict]] = {}
    for row in rows:
        archivo = dict(row)
        agrupados.setdefault(int(archivo.pop("message_id")), []).append(archivo)
    return agrupados

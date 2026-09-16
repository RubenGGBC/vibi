"""Persistencia y permisos del coordinador de equipos humanos."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from . import db
from .equipo_senales import Senal


class EquipoError(ValueError):
    pass


SONDA_POR_SENAL = {
    "avance": "archivo",
    "sin_avance": "archivo",
    "entregado": "archivo",
    "fallo_repetido": "proceso",
    "tarea_larga": "proceso",
    "revision_pendiente": "web",
    "integracion_rota": "web",
}


def crear_tablas() -> None:
    with db._conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS equipos (
            id          TEXT PRIMARY KEY,
            nombre      TEXT NOT NULL,
            creado_por  TEXT NOT NULL REFERENCES users(id),
            creado_en   REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS equipo_miembros (
            equipo_id   TEXT NOT NULL REFERENCES equipos(id),
            user_id     TEXT NOT NULL REFERENCES users(id),
            rol         TEXT NOT NULL CHECK (rol IN ('coordinador', 'miembro')),
            estado      TEXT NOT NULL DEFAULT 'activo'
                        CHECK (estado IN ('activo', 'retirado')),
            alta_en     REAL NOT NULL,
            PRIMARY KEY (equipo_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS equipo_tareas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id   TEXT NOT NULL REFERENCES equipos(id),
            titulo      TEXT NOT NULL,
            asignada_a  TEXT REFERENCES users(id),
            estado      TEXT NOT NULL DEFAULT 'abierta'
                        CHECK (estado IN ('abierta', 'en_progreso',
                                          'esperando_revision', 'entregada',
                                          'cerrada')),
            abierta_en  REAL NOT NULL,
            actualizada_en REAL NOT NULL,
            cerrada_en  REAL
        );
        CREATE TABLE IF NOT EXISTS equipo_seguimientos (
            id            TEXT PRIMARY KEY,
            equipo_id     TEXT NOT NULL REFERENCES equipos(id),
            tarea_id      INTEGER NOT NULL REFERENCES equipo_tareas(id),
            user_id       TEXT NOT NULL REFERENCES users(id),
            node_id       TEXT NOT NULL REFERENCES nodes(id),
            sonda         TEXT NOT NULL CHECK (sonda IN ('archivo','proceso','web')),
            senal         TEXT NOT NULL,
            parametros    TEXT NOT NULL,
            justificacion TEXT NOT NULL,
            estado        TEXT NOT NULL DEFAULT 'propuesto'
                          CHECK (estado IN ('propuesto','aprobado','rechazado','revocado')),
            propuesto_por TEXT NOT NULL REFERENCES users(id),
            propuesta_en  REAL NOT NULL,
            decidida_en   REAL,
            revocada_en   REAL
        );
        CREATE INDEX IF NOT EXISTS idx_equipo_seguimientos_nodo
            ON equipo_seguimientos(node_id, estado);
        CREATE TABLE IF NOT EXISTS equipo_senales (
            id             TEXT PRIMARY KEY,
            seguimiento_id TEXT NOT NULL REFERENCES equipo_seguimientos(id),
            equipo_id      TEXT NOT NULL REFERENCES equipos(id),
            tarea_id       INTEGER NOT NULL REFERENCES equipo_tareas(id),
            user_id        TEXT NOT NULL REFERENCES users(id),
            nombre         TEXT NOT NULL,
            payload        TEXT NOT NULL,
            secuencia      INTEGER NOT NULL,
            observada_en   REAL NOT NULL,
            recibida_en    REAL NOT NULL,
            UNIQUE(seguimiento_id, secuencia)
        );
        CREATE TABLE IF NOT EXISTS equipo_creencias (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id     TEXT NOT NULL REFERENCES equipos(id),
            tarea_id      INTEGER REFERENCES equipo_tareas(id),
            user_id       TEXT REFERENCES users(id),
            clave         TEXT NOT NULL,
            clase         TEXT NOT NULL CHECK (clase IN
                           ('estado','bloqueo','competencia','disponibilidad')),
            valor         TEXT NOT NULL,
            procedencia   TEXT NOT NULL CHECK (procedencia IN
                           ('observacion','declaracion','inferencia')),
            confianza     REAL NOT NULL CHECK (confianza >= 0 AND confianza <= 1),
            senal_id      TEXT REFERENCES equipo_senales(id),
            vista_en      REAL NOT NULL,
            caduca_en     REAL NOT NULL,
            reemplazada_en REAL
        );
        CREATE INDEX IF NOT EXISTS idx_equipo_creencias_vigentes
            ON equipo_creencias(equipo_id, reemplazada_en, caduca_en);
        CREATE TABLE IF NOT EXISTS equipo_iniciativas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id     TEXT NOT NULL REFERENCES equipos(id),
            tarea_id      INTEGER REFERENCES equipo_tareas(id),
            destinatario  TEXT NOT NULL REFERENCES users(id),
            clase         TEXT NOT NULL,
            texto         TEXT NOT NULL,
            prioridad     INTEGER NOT NULL,
            dedupe        TEXT NOT NULL,
            estado        TEXT NOT NULL DEFAULT 'pendiente'
                          CHECK (estado IN ('pendiente','entregada','descartada')),
            creada_en     REAL NOT NULL,
            entregada_en  REAL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_equipo_iniciativa_pendiente
            ON equipo_iniciativas(destinatario, dedupe)
            WHERE estado='pendiente';
        """)


def _texto(valor: object, limite: int, campo: str) -> str:
    limpio = " ".join(str(valor or "").split())[:limite]
    if not limpio:
        raise EquipoError(f"{campo} no puede estar vacío")
    return limpio


def crear(nombre: str, user_id: str) -> dict:
    equipo_id, ahora = str(uuid.uuid4()), time.time()
    with db._conn() as c:
        c.execute(
            "INSERT INTO equipos (id,nombre,creado_por,creado_en) VALUES (?,?,?,?)",
            (equipo_id, _texto(nombre, 120, "nombre"), user_id, ahora),
        )
        c.execute(
            """INSERT INTO equipo_miembros
               (equipo_id,user_id,rol,estado,alta_en)
               VALUES (?,?,'coordinador','activo',?)""",
            (equipo_id, user_id, ahora),
        )
    return obtener(equipo_id, user_id)


def _miembro(c, equipo_id: str, user_id: str):
    return c.execute(
        """SELECT * FROM equipo_miembros
           WHERE equipo_id=? AND user_id=? AND estado='activo'""",
        (equipo_id, user_id),
    ).fetchone()


def obtener(equipo_id: str, user_id: str) -> dict | None:
    with db._conn() as c:
        if not _miembro(c, equipo_id, user_id):
            return None
        fila = c.execute("SELECT * FROM equipos WHERE id=?", (equipo_id,)).fetchone()
        if not fila:
            return None
        salida = dict(fila)
        salida["miembros"] = [
            dict(r) for r in c.execute(
                """SELECT m.user_id, u.nombre, m.rol, m.estado, m.alta_en,
                          COALESCE(a.color_cara, '#FFFFFF') AS color_cara,
                          COALESCE(a.color_antifaz, '#0C0714') AS color_antifaz,
                          COALESCE(a.color_sombrero, '#F4121B') AS color_sombrero
                   FROM equipo_miembros m JOIN users u ON u.id=m.user_id
                   LEFT JOIN user_appearance a ON a.user_id=m.user_id
                   WHERE m.equipo_id=? AND m.estado='activo' ORDER BY m.alta_en""",
                (equipo_id,),
            )
        ]
        salida["mi_rol"] = next(
            m["rol"] for m in salida["miembros"] if m["user_id"] == user_id
        )
        return salida


def listar(user_id: str) -> list[dict]:
    with db._conn() as c:
        ids = [
            str(r["equipo_id"]) for r in c.execute(
                """SELECT equipo_id FROM equipo_miembros
                   WHERE user_id=? AND estado='activo' ORDER BY alta_en""",
                (user_id,),
            )
        ]
    return [e for equipo_id in ids if (e := obtener(equipo_id, user_id))]


def anadir_miembro(equipo_id: str, actor_id: str, nombre: str) -> dict:
    usuario = db.get_user_by_nombre(_texto(nombre, 120, "nombre"))
    if not usuario:
        raise EquipoError("No existe una persona de Vibi con ese nombre")
    ahora = time.time()
    with db._conn() as c:
        actor = _miembro(c, equipo_id, actor_id)
        if not actor or actor["rol"] != "coordinador":
            raise EquipoError("Solo quien coordina puede añadir miembros")
        c.execute(
            """INSERT INTO equipo_miembros
               (equipo_id,user_id,rol,estado,alta_en)
               VALUES (?,?,'miembro','activo',?)
               ON CONFLICT(equipo_id,user_id) DO UPDATE SET estado='activo'""",
            (equipo_id, usuario["id"], ahora),
        )
    return obtener(equipo_id, actor_id)


def crear_tarea(equipo_id: str, actor_id: str, titulo: str, asignada_a: str) -> dict:
    ahora = time.time()
    with db._conn() as c:
        if not _miembro(c, equipo_id, actor_id):
            raise EquipoError("No perteneces a este equipo")
        if not _miembro(c, equipo_id, asignada_a):
            raise EquipoError("La persona asignada no pertenece al equipo")
        cursor = c.execute(
            """INSERT INTO equipo_tareas
               (equipo_id,titulo,asignada_a,estado,abierta_en,actualizada_en)
               VALUES (?,?,?,'abierta',?,?)""",
            (equipo_id, _texto(titulo, 200, "título"), asignada_a, ahora, ahora),
        )
        tarea_id = cursor.lastrowid
        fila = c.execute("SELECT * FROM equipo_tareas WHERE id=?", (tarea_id,)).fetchone()
    return dict(fila)


def tareas(equipo_id: str, user_id: str) -> list[dict]:
    with db._conn() as c:
        if not _miembro(c, equipo_id, user_id):
            raise EquipoError("No perteneces a este equipo")
        return [
            dict(r) for r in c.execute(
                """SELECT t.*, u.nombre AS asignada_nombre
                   FROM equipo_tareas t LEFT JOIN users u ON u.id=t.asignada_a
                   WHERE t.equipo_id=? ORDER BY t.actualizada_en DESC""",
                (equipo_id,),
            )
        ]


def _validar_parametros(senal: str, parametros: object) -> dict:
    if not isinstance(parametros, dict):
        raise EquipoError("Los parámetros tienen que ser un objeto")
    permitidos = {
        "avance": {"ruta"},
        "sin_avance": {"ruta", "horas"},
        "entregado": {"ruta"},
        "fallo_repetido": {"trabajo", "veces"},
        "tarea_larga": {"trabajo", "minutos"},
        "revision_pendiente": {"app", "puerto", "pestana", "selector"},
        "integracion_rota": {"app", "puerto", "pestana", "selector"},
    }[senal]
    if set(parametros) - permitidos:
        raise EquipoError("La propuesta contiene parámetros desconocidos")
    if senal in {"avance", "sin_avance", "entregado"} and not parametros.get("ruta"):
        raise EquipoError("Hace falta una ruta concreta")
    if senal in {"fallo_repetido", "tarea_larga"} and not parametros.get("trabajo"):
        raise EquipoError("Hace falta el identificador del trabajo supervisado")
    if senal in {"revision_pendiente", "integracion_rota"} and not parametros.get("selector"):
        raise EquipoError("Hace falta un selector web concreto")
    return {k: parametros[k] for k in permitidos if k in parametros}


def proponer_seguimiento(
    equipo_id: str,
    tarea_id: int,
    actor_id: str,
    node_id: str,
    senal: str,
    parametros: object,
    justificacion: str,
) -> dict:
    if senal not in SONDA_POR_SENAL:
        raise EquipoError("Esa señal no nace de un seguimiento de nodo")
    ahora, seguimiento_id = time.time(), str(uuid.uuid4())
    with db._conn() as c:
        actor = _miembro(c, equipo_id, actor_id)
        if not actor:
            raise EquipoError("No perteneces a este equipo")
        tarea = c.execute(
            "SELECT * FROM equipo_tareas WHERE id=? AND equipo_id=?",
            (tarea_id, equipo_id),
        ).fetchone()
        if not tarea or not tarea["asignada_a"]:
            raise EquipoError("La tarea no existe o no tiene responsable")
        if actor["rol"] != "coordinador" and actor_id != tarea["asignada_a"]:
            raise EquipoError("Solo quien coordina o tiene la tarea puede proponerla")
        if not node_id:
            candidatos = db.list_nodes(tarea["asignada_a"])
            if not candidatos:
                raise EquipoError("La persona asignada no tiene un dispositivo activo")
            node_id = str(candidatos[0]["id"])
        nodo = db.get_node_for_user(node_id, tarea["asignada_a"])
        if not nodo:
            raise EquipoError("El dispositivo no pertenece a la persona asignada")
        limpios = _validar_parametros(senal, parametros)
        c.execute(
            """INSERT INTO equipo_seguimientos
               (id,equipo_id,tarea_id,user_id,node_id,sonda,senal,parametros,
                justificacion,estado,propuesto_por,propuesta_en)
               VALUES (?,?,?,?,?,?,?,?,?,'propuesto',?,?)""",
            (
                seguimiento_id, equipo_id, tarea_id, tarea["asignada_a"], node_id,
                SONDA_POR_SENAL[senal], senal,
                json.dumps(limpios, ensure_ascii=False),
                _texto(justificacion, 300, "justificación"), actor_id, ahora,
            ),
        )
        fila = c.execute(
            "SELECT * FROM equipo_seguimientos WHERE id=?", (seguimiento_id,)
        ).fetchone()
    return _seguimiento(fila)


def _seguimiento(fila) -> dict:
    salida = dict(fila)
    try:
        salida["parametros"] = json.loads(salida["parametros"])
    except (TypeError, ValueError):
        salida["parametros"] = {}
    return salida


def seguimientos_pendientes(user_id: str) -> list[dict]:
    with db._conn() as c:
        filas = c.execute(
            """SELECT s.*, t.titulo AS tarea_titulo, e.nombre AS equipo_nombre,
                      n.nombre AS node_nombre
               FROM equipo_seguimientos s
               JOIN equipo_tareas t ON t.id=s.tarea_id
               JOIN equipos e ON e.id=s.equipo_id
               JOIN nodes n ON n.id=s.node_id
               WHERE s.user_id=? AND s.estado='propuesto'
               ORDER BY s.propuesta_en""",
            (user_id,),
        ).fetchall()
    return [_seguimiento(f) for f in filas]


def decidir_seguimiento(seguimiento_id: str, user_id: str, aprobar: bool) -> dict:
    ahora = time.time()
    with db._conn() as c:
        fila = c.execute(
            "SELECT * FROM equipo_seguimientos WHERE id=?", (seguimiento_id,)
        ).fetchone()
        if not fila or fila["user_id"] != user_id:
            raise EquipoError("Seguimiento no encontrado")
        if fila["estado"] != "propuesto":
            raise EquipoError("Ese seguimiento ya fue decidido")
        c.execute(
            "UPDATE equipo_seguimientos SET estado=?, decidida_en=? WHERE id=?",
            ("aprobado" if aprobar else "rechazado", ahora, seguimiento_id),
        )
        fila = c.execute(
            "SELECT * FROM equipo_seguimientos WHERE id=?", (seguimiento_id,)
        ).fetchone()
    return _seguimiento(fila)


def revocar_seguimiento(seguimiento_id: str, user_id: str) -> dict:
    with db._conn() as c:
        fila = c.execute(
            "SELECT * FROM equipo_seguimientos WHERE id=?", (seguimiento_id,)
        ).fetchone()
        if not fila or fila["user_id"] != user_id:
            raise EquipoError("Seguimiento no encontrado")
        c.execute(
            """UPDATE equipo_seguimientos
               SET estado='revocado', revocada_en=? WHERE id=?""",
            (time.time(), seguimiento_id),
        )
        # Una observación retirada no conserva autoridad silenciosamente. Las
        # declaraciones independientes, si las hay, no se tocan.
        ahora = time.time()
        c.execute(
            """UPDATE equipo_creencias SET caduca_en=MIN(caduca_en, ?)
               WHERE reemplazada_en IS NULL AND senal_id IN (
                   SELECT id FROM equipo_senales WHERE seguimiento_id=?
               )""",
            (ahora, seguimiento_id),
        )
        fila = c.execute(
            "SELECT * FROM equipo_seguimientos WHERE id=?", (seguimiento_id,)
        ).fetchone()
    return _seguimiento(fila)


def suscripcion(node_id: str) -> list[dict]:
    with db._conn() as c:
        filas = c.execute(
            """SELECT * FROM equipo_seguimientos
               WHERE node_id=? AND estado='aprobado' ORDER BY propuesta_en""",
            (node_id,),
        ).fetchall()
    return [
        {
            "id": f["id"], "senal": f["senal"], "sonda": f["sonda"],
            "parametros": json.loads(f["parametros"]), "intervalo": 10.0,
        }
        for f in filas
    ]


def guardar_senal(node_id: str, senal: Senal) -> dict | None:
    """Guarda una señal una sola vez; ``None`` significa duplicada."""
    ahora = time.time()
    with db._conn() as c:
        seguimiento = c.execute(
            "SELECT * FROM equipo_seguimientos WHERE id=?",
            (senal.seguimiento,),
        ).fetchone()
        if not seguimiento or seguimiento["estado"] != "aprobado":
            raise EquipoError("La señal no corresponde a un seguimiento aprobado")
        if seguimiento["node_id"] != node_id or seguimiento["senal"] != senal.nombre:
            raise EquipoError("La señal no corresponde a este nodo o seguimiento")
        try:
            c.execute(
                """INSERT INTO equipo_senales
                   (id,seguimiento_id,equipo_id,tarea_id,user_id,nombre,payload,
                    secuencia,observada_en,recibida_en)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    senal.id, senal.seguimiento, seguimiento["equipo_id"],
                    seguimiento["tarea_id"], seguimiento["user_id"], senal.nombre,
                    json.dumps(senal.payload, ensure_ascii=False), senal.secuencia,
                    senal.observada_en, ahora,
                ),
            )
        except Exception as error:
            # Los dos índices de idempotencia pueden chocar durante reintentos.
            if "UNIQUE constraint failed" in str(error):
                return None
            raise
        fila = c.execute("SELECT * FROM equipo_senales WHERE id=?", (senal.id,)).fetchone()
    salida = dict(fila)
    salida["payload"] = json.loads(salida["payload"])
    return salida


def creer(
    *, equipo_id: str, tarea_id: int | None, user_id: str | None, clave: str,
    clase: str, valor: str, procedencia: str, confianza: float,
    vista_en: float, caduca_en: float, senal_id: str | None,
) -> dict:
    with db._conn() as c:
        vigente = c.execute(
            """SELECT * FROM equipo_creencias
               WHERE equipo_id=? AND clave=? AND reemplazada_en IS NULL""",
            (equipo_id, clave),
        ).fetchone()
        if vigente:
            if float(vigente["vista_en"]) > vista_en:
                return dict(vigente)
            if (
                vigente["procedencia"] == "observacion"
                and procedencia != "observacion"
                and float(vigente["caduca_en"]) > time.time()
            ):
                return dict(vigente)
        c.execute(
            """UPDATE equipo_creencias SET reemplazada_en=?
               WHERE equipo_id=? AND clave=? AND reemplazada_en IS NULL""",
            (vista_en, equipo_id, clave),
        )
        cursor = c.execute(
            """INSERT INTO equipo_creencias
               (equipo_id,tarea_id,user_id,clave,clase,valor,procedencia,
                confianza,senal_id,vista_en,caduca_en,reemplazada_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)""",
            (
                equipo_id, tarea_id, user_id, clave, clase, valor, procedencia,
                max(0.0, min(1.0, confianza)), senal_id, vista_en, caduca_en,
            ),
        )
        fila = c.execute(
            "SELECT * FROM equipo_creencias WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
    return dict(fila)


def cambiar_estado_tarea(tarea_id: int, estado: str, ahora: float) -> None:
    with db._conn() as c:
        c.execute(
            """UPDATE equipo_tareas SET estado=?, actualizada_en=?,
               cerrada_en=CASE WHEN ?='cerrada' THEN ? ELSE cerrada_en END
               WHERE id=?""",
            (estado, ahora, estado, ahora, tarea_id),
        )


def encolar_iniciativa(
    equipo_id: str, tarea_id: int | None, destinatario: str,
    clase: str, texto: str, prioridad: int, dedupe: str,
) -> None:
    with db._conn() as c:
        c.execute(
            """INSERT OR IGNORE INTO equipo_iniciativas
               (equipo_id,tarea_id,destinatario,clase,texto,prioridad,dedupe,
                estado,creada_en)
               VALUES (?,?,?,?,?,?,?,'pendiente',?)""",
            (
                equipo_id, tarea_id, destinatario, clase, texto,
                prioridad, dedupe, time.time(),
            ),
        )


def iniciativas_pendientes() -> list[dict]:
    with db._conn() as c:
        return [
            dict(r) for r in c.execute(
                """SELECT * FROM equipo_iniciativas WHERE estado='pendiente'
                   ORDER BY destinatario, prioridad DESC, creada_en"""
            )
        ]


def gastadas_hoy(user_id: str, ahora: float | None = None) -> int:
    momento = time.time() if ahora is None else ahora
    local = datetime.fromtimestamp(momento).astimezone()
    comienzo = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with db._conn() as c:
        fila = c.execute(
            """SELECT COUNT(*) AS total FROM equipo_iniciativas
               WHERE destinatario=? AND estado='entregada' AND entregada_en>=?""",
            (user_id, comienzo),
        ).fetchone()
    return int(fila["total"] or 0)


def declarar_estado(
    equipo_id: str, tarea_id: int, user_id: str, estado: str
) -> dict:
    permitidos = {"abierta", "en_progreso", "esperando_revision", "entregada", "cerrada"}
    if estado not in permitidos:
        raise EquipoError("Estado declarado desconocido")
    ahora = time.time()
    with db._conn() as c:
        if not _miembro(c, equipo_id, user_id):
            raise EquipoError("No perteneces a este equipo")
        tarea = c.execute(
            "SELECT * FROM equipo_tareas WHERE id=? AND equipo_id=?",
            (tarea_id, equipo_id),
        ).fetchone()
        if not tarea or tarea["asignada_a"] != user_id:
            raise EquipoError("Solo quien tiene la tarea puede declarar su estado")
    creencia = creer(
        equipo_id=equipo_id,
        tarea_id=tarea_id,
        user_id=user_id,
        clave=f"tarea:{tarea_id}:estado",
        clase="estado",
        valor=estado,
        procedencia="declaracion",
        confianza=0.5,
        vista_en=ahora,
        caduca_en=ahora + 24 * 3600,
        senal_id=None,
    )
    # Si una observación vigente ganó, su valor es también el estado material.
    cambiar_estado_tarea(tarea_id, creencia["valor"], ahora)
    return creencia


def marcar_iniciativa(iniciativa_id: int, estado: str) -> None:
    with db._conn() as c:
        c.execute(
            """UPDATE equipo_iniciativas SET estado=?, entregada_en=?
               WHERE id=? AND estado='pendiente'""",
            (estado, time.time() if estado == "entregada" else None, iniciativa_id),
        )


def panel(equipo_id: str, user_id: str) -> dict:
    equipo = obtener(equipo_id, user_id)
    if not equipo:
        raise EquipoError("Equipo no encontrado")
    ahora = time.time()
    with db._conn() as c:
        tareas_lista = [
            dict(r) for r in c.execute(
                """SELECT t.*, u.nombre AS asignada_nombre
                   FROM equipo_tareas t LEFT JOIN users u ON u.id=t.asignada_a
                   WHERE t.equipo_id=? ORDER BY t.actualizada_en DESC""",
                (equipo_id,),
            )
        ]
        creencias = [
            dict(r) for r in c.execute(
                """SELECT * FROM equipo_creencias
                   WHERE equipo_id=? AND reemplazada_en IS NULL AND caduca_en>?
                   ORDER BY vista_en DESC""",
                (equipo_id, ahora),
            )
        ]
        senales = [
            dict(r) for r in c.execute(
                """SELECT id,tarea_id,user_id,nombre,payload,observada_en,recibida_en
                   FROM equipo_senales WHERE equipo_id=?
                   ORDER BY recibida_en DESC LIMIT 50""",
                (equipo_id,),
            )
        ]
        seguimientos = [
            _seguimiento(r) for r in c.execute(
                """SELECT * FROM equipo_seguimientos WHERE equipo_id=?
                   ORDER BY propuesta_en DESC""",
                (equipo_id,),
            )
        ]
    for senal in senales:
        senal["payload"] = json.loads(senal["payload"])
    # Los parámetros locales solo los ve la persona cuyo nodo los observa.
    for seguimiento in seguimientos:
        if seguimiento["user_id"] != user_id:
            seguimiento["parametros"] = {}
    return {
        "equipo": equipo,
        "tareas": tareas_lista,
        "creencias": creencias,
        "senales": senales,
        "seguimientos": seguimientos,
    }

"""Lo que Vibi cree saber de quién tiene delante.

**Una afirmación no es un dato, es una hipótesis.** «Estudia medicina» puede
venir de que lo dijo en la entrevista, de que tiene una carpeta llamada
Farmacología, o de que lleva un mes abriendo PDF de ese tema. Las tres cosas
no valen lo mismo, y por eso cada afirmación guarda **de dónde salió** y
**cuánta confianza tiene**.

Es la disciplina de `recetas.py` —solo lo verificado vale— aplicada al perfil,
con una diferencia deliberada: una receta mala hace fallar la tarea y por eso
se retira sola; una afirmación floja solo hace que sobre una herramienta, así
que baja de nivel y la retirada se propone.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse

from . import db

CLASES = frozenset({"dominio", "rasgo", "herramienta", "preferencia", "aficion"})

# `rasgo` es quién es la persona —cómo trabaja, qué le importa, su forma de
# ser—, no cómo hay que hablarle. La distinción importa porque una afirmación
# de trato sería una orden al modelo y aquí todo es una hipótesis con
# confianza: «es directo» puede decaer si lo observado lo contradice, «sé
# breve» no tendría con qué contradecirse.
PROCEDENCIAS = frozenset({"entrevista", "inventario", "uso"})

# Con cuánta confianza nace una afirmación según quién la trajo. El uso pesa
# más que lo declarado porque lo que alguien hace dice más que lo que dice que
# hace; el inventario pesa menos porque una carpeta llamada «Bioquímica» puede
# ser de otra persona.
CONFIANZA_INICIAL = {"entrevista": 0.6, "inventario": 0.4, "uso": 0.8}


class PerfilError(Exception):
    """Algo que impide guardar o mover el perfil."""


class PerfilInvalido(PerfilError):
    pass


def crear_tablas() -> None:
    with db._conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS perfil (
            user_id      TEXT PRIMARY KEY,
            resumen      TEXT NOT NULL DEFAULT '',
            creado_en    REAL NOT NULL,
            revisado_en  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS perfil_afirmaciones (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT NOT NULL,
            clase        TEXT NOT NULL,
            valor        TEXT NOT NULL,
            procedencia  TEXT NOT NULL,
            confianza    REAL NOT NULL,
            apoyos       INTEGER NOT NULL DEFAULT 0,
            contras      INTEGER NOT NULL DEFAULT 0,
            creada_en    REAL NOT NULL,
            movida_en    REAL NOT NULL,
            UNIQUE(user_id, clase, valor)
        );

        CREATE TABLE IF NOT EXISTS perfil_capacidades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL,
            tipo          TEXT NOT NULL,
            referencia    TEXT NOT NULL,
            justificacion TEXT NOT NULL,
            transporte    TEXT NOT NULL DEFAULT '',
            nivel         TEXT NOT NULL DEFAULT 'completo',
            aprobada_en   REAL,
            usos          INTEGER NOT NULL DEFAULT 0,
            ultimo_uso    REAL,
            endpoint      TEXT NOT NULL DEFAULT '',
            revisiones_sin_uso INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, tipo, referencia)
        );

        CREATE TABLE IF NOT EXISTS perfil_propuestas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL,
            tipo          TEXT NOT NULL,
            referencia    TEXT NOT NULL,
            bloque        TEXT NOT NULL,
            estado        TEXT NOT NULL DEFAULT 'pendiente',
            propuesta_en  REAL NOT NULL,
            decidida_en   REAL,
            UNIQUE(user_id, tipo, referencia)
        );

        CREATE TABLE IF NOT EXISTS perfil_mcp_retirados (
            user_id       TEXT NOT NULL,
            referencia    TEXT NOT NULL,
            PRIMARY KEY(user_id, referencia)
        );

        CREATE TABLE IF NOT EXISTS perfil_capacidades_retiradas (
            user_id       TEXT NOT NULL,
            tipo          TEXT NOT NULL,
            referencia    TEXT NOT NULL,
            PRIMARY KEY(user_id, tipo, referencia)
        );
        """)
        columnas = {
            str(fila["name"])
            for fila in c.execute("PRAGMA table_info(perfil_capacidades)")
        }
        if "endpoint" not in columnas:
            c.execute(
                "ALTER TABLE perfil_capacidades ADD COLUMN endpoint TEXT NOT NULL DEFAULT ''"
            )
        if "revisiones_sin_uso" not in columnas:
            c.execute(
                "ALTER TABLE perfil_capacidades "
                "ADD COLUMN revisiones_sin_uso INTEGER NOT NULL DEFAULT 0"
            )
        c.execute(
            """INSERT OR IGNORE INTO perfil_capacidades_retiradas
               (user_id, tipo, referencia)
               SELECT user_id, 'mcp', referencia FROM perfil_mcp_retirados"""
        )


def _asegurar_perfil(c, user_id: str, ahora: float) -> None:
    c.execute(
        """INSERT INTO perfil (user_id, resumen, creado_en, revisado_en)
           VALUES (?, '', ?, ?)
           ON CONFLICT(user_id) DO NOTHING""",
        (user_id, ahora, ahora),
    )


def _normalizar(valor: object) -> str:
    return " ".join(str(valor or "").split()).casefold()


def afirmar(user_id: str, clase: str, valor: object, procedencia: str) -> dict:
    """Apunta algo que se cree del usuario, con quién lo trajo.

    Si ya estaba, **no se duplica ni se pisa la confianza acumulada**: solo se
    anota la procedencia más fuerte. Una afirmación que ya llevaba semanas
    sosteniéndose con el uso no vuelve a 0,6 porque alguien la repita en una
    entrevista.
    """
    if clase not in CLASES:
        raise PerfilInvalido(
            f"«{clase}» no es una clase de afirmación; son {', '.join(sorted(CLASES))}"
        )
    if procedencia not in PROCEDENCIAS:
        raise PerfilInvalido(
            f"«{procedencia}» no es una procedencia; son {', '.join(sorted(PROCEDENCIAS))}"
        )
    texto = _normalizar(valor)
    if not texto:
        raise PerfilInvalido("Una afirmación vacía no dice nada del usuario")

    ahora = time.time()
    inicial = CONFIANZA_INICIAL[procedencia]
    with db._conn() as c:
        _asegurar_perfil(c, user_id, ahora)
        fila = c.execute(
            "SELECT * FROM perfil_afirmaciones WHERE user_id=? AND clase=? AND valor=?",
            (user_id, clase, texto),
        ).fetchone()
        if fila:
            if inicial > fila["confianza"]:
                c.execute(
                    "UPDATE perfil_afirmaciones SET procedencia=?, confianza=?, movida_en=? WHERE id=?",
                    (procedencia, inicial, ahora, fila["id"]),
                )
        else:
            c.execute(
                """INSERT INTO perfil_afirmaciones
                   (user_id, clase, valor, procedencia, confianza, creada_en, movida_en)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, clase, texto, procedencia, inicial, ahora, ahora),
            )
    return [a for a in afirmaciones_de(user_id, clase) if a["valor"] == texto][0]


def afirmaciones_de(user_id: str, clase: str | None = None) -> list[dict]:
    consulta = "SELECT * FROM perfil_afirmaciones WHERE user_id=?"
    parametros: list = [user_id]
    if clase:
        consulta += " AND clase=?"
        parametros.append(clase)
    with db._conn() as c:
        return [dict(f) for f in c.execute(consulta + " ORDER BY id", parametros)]


# Cuánto se mueve la confianza en cada dirección. La contradicción pesa el
# triple que un apoyo a propósito: acertar una vez puede ser casualidad, pero
# que el usuario haga justo lo contrario de lo que se creía es información.
APOYO = 0.10
CONTRADICCION = 0.30
# Y lo que se pierde por no aparecer en una revisión entera. Va despacio
# porque hay cosas que se hacen una vez al mes y siguen importando.
DECAIMIENTO = 0.05


def _mover(user_id: str, clase: str, valor: object, delta: float, campo: str | None) -> None:
    texto = _normalizar(valor)
    ahora = time.time()
    with db._conn() as c:
        fila = c.execute(
            "SELECT * FROM perfil_afirmaciones WHERE user_id=? AND clase=? AND valor=?",
            (user_id, clase, texto),
        ).fetchone()
        if not fila:
            return
        nueva = min(1.0, max(0.0, fila["confianza"] + delta))
        if campo:
            c.execute(
                f"UPDATE perfil_afirmaciones SET confianza=?, {campo}={campo}+1, movida_en=? WHERE id=?",
                (nueva, ahora, fila["id"]),
            )
        else:
            c.execute(
                "UPDATE perfil_afirmaciones SET confianza=?, movida_en=? WHERE id=?",
                (nueva, ahora, fila["id"]),
            )


def apoyar(user_id: str, clase: str, valor: object) -> None:
    """El uso ha confirmado esto."""
    _mover(user_id, clase, valor, APOYO, "apoyos")


def contradecir(user_id: str, clase: str, valor: object) -> None:
    """El uso dice lo contrario de esto."""
    _mover(user_id, clase, valor, -CONTRADICCION, "contras")


def decaer(user_id: str, sin_uso: list[tuple[str, str]]) -> None:
    """Lo que no ha aparecido en toda la revisión pierde un poco de fuerza."""
    for clase, valor in sin_uso:
        _mover(user_id, clase, valor, -DECAIMIENTO, None)


TIPOS = frozenset({"mcp", "skill", "vigilancia"})
NIVELES = ("completo", "catalogo", "propuesta_retirada")

# A partir de dónde una capacidad entra entera en el contexto, y a partir de
# dónde solo se recuerda. No es un capricho: cada servidor MCP declarado mete
# sus esquemas en todos los turnos, y por eso el catálogo de `agy` bajó de 97
# a 65 esquemas cuando se podó.
UMBRAL_COMPLETO = 0.6
UMBRAL_CATALOGO = 0.3


def nivel_para(confianza: float) -> str:
    if confianza >= UMBRAL_COMPLETO:
        return "completo"
    if confianza >= UMBRAL_CATALOGO:
        return "catalogo"
    return "propuesta_retirada"


# Cuántas revisiones seguidas sin usarse aguanta una capacidad en cada nivel.
# Son semanas, porque la revisión es semanal: un mes largo desde que se aprueba
# algo hasta que se propone quitarlo.
#
# Hace falta un contador propio y no basta la confianza de las afirmaciones que
# la sostienen, porque casi ninguna capacidad tiene ninguna: la justificación
# viene del registro público y está en inglés, y el usuario habló en español.
# Antes ese hueco se leía como confianza 0,0 y mataba toda capacidad en la
# primera revisión, que es justo lo contrario de lo que dice el diseño.
DESUSO_A_CATALOGO = 2
DESUSO_A_RETIRADA = 3


def nivel_por_desuso(revisiones: int) -> str:
    if revisiones >= DESUSO_A_RETIRADA:
        return "propuesta_retirada"
    if revisiones >= DESUSO_A_CATALOGO:
        return "catalogo"
    return "completo"


def peor_nivel(*niveles: str) -> str:
    """El más conservador de varios veredictos sobre la misma capacidad."""
    return max(niveles, key=NIVELES.index)


def anotar_desuso(user_id: str, tipo: str, referencia: str) -> int:
    """Una revisión más sin aparecer. Devuelve cuántas lleva seguidas."""
    with db._conn() as c:
        c.execute(
            """UPDATE perfil_capacidades
               SET revisiones_sin_uso = revisiones_sin_uso + 1
               WHERE user_id=? AND tipo=? AND referencia=?""",
            (user_id, tipo, referencia),
        )
        fila = c.execute(
            """SELECT revisiones_sin_uso FROM perfil_capacidades
               WHERE user_id=? AND tipo=? AND referencia=?""",
            (user_id, tipo, referencia),
        ).fetchone()
    return int(fila["revisiones_sin_uso"]) if fila else 0


def aprobar_capacidad(
    user_id: str,
    tipo: str,
    referencia: str,
    justificacion: str,
    transporte: str = "",
    endpoint: str = "",
) -> dict:
    """El usuario ha dicho que sí a esto.

    `justificacion` no admite vacío: es lo que se le enseña el día que se le
    proponga retirarla, y sin ella la propuesta es «quita esto porque sí».
    """
    if tipo not in TIPOS:
        raise PerfilInvalido(
            f"«{tipo}» no es un tipo de capacidad; son {', '.join(sorted(TIPOS))}"
        )
    if transporte not in ("", "remoto", "local"):
        raise PerfilInvalido(f"«{transporte}» no es un transporte conocido")
    referencia = str(referencia or "").strip()
    if not referencia:
        raise PerfilInvalido("Una capacidad necesita una referencia")
    endpoint = str(endpoint or "").strip()
    if tipo == "mcp" and transporte == "local":
        raise PerfilInvalido(
            "Los MCP locales no se pueden aprobar hasta disponer de un instalador seguro"
        )
    if tipo == "mcp" and transporte == "remoto":
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PerfilInvalido("Un MCP remoto necesita un endpoint HTTP válido")
    motivo = str(justificacion or "").strip()
    if not motivo:
        raise PerfilInvalido("Una capacidad sin justificación no se puede revisar después")

    ahora = time.time()
    with db._conn() as c:
        _asegurar_perfil(c, user_id, ahora)
        c.execute(
            """INSERT INTO perfil_capacidades
               (user_id, tipo, referencia, justificacion, transporte, nivel, aprobada_en, endpoint)
               VALUES (?, ?, ?, ?, ?, 'completo', ?, ?)
               ON CONFLICT(user_id, tipo, referencia) DO UPDATE SET
                   justificacion = excluded.justificacion,
                   transporte = excluded.transporte,
                   nivel = 'completo',
                   aprobada_en = excluded.aprobada_en,
                   endpoint = excluded.endpoint""",
            (user_id, tipo, referencia, motivo, transporte, ahora, endpoint),
        )
        c.execute(
            """DELETE FROM perfil_capacidades_retiradas
               WHERE user_id=? AND tipo=? AND referencia=?""",
            (user_id, tipo, referencia),
        )
    return [
        cap for cap in capacidades_de(user_id, tipo) if cap["referencia"] == referencia
    ][0]


def capacidades_de(user_id: str, tipo: str | None = None) -> list[dict]:
    consulta = "SELECT * FROM perfil_capacidades WHERE user_id=?"
    parametros: list = [user_id]
    if tipo:
        consulta += " AND tipo=?"
        parametros.append(tipo)
    with db._conn() as c:
        return [dict(f) for f in c.execute(consulta + " ORDER BY id", parametros)]


def registrar_uso_capacidad(user_id: str, tipo: str, referencia: str) -> None:
    with db._conn() as c:
        c.execute(
            """UPDATE perfil_capacidades
               SET usos = usos + 1, ultimo_uso = ?, revisiones_sin_uso = 0
               WHERE user_id=? AND tipo=? AND referencia=?""",
            (time.time(), user_id, tipo, referencia),
        )


def registrar_uso_por_alias(
    user_id: str, tipo: str, referencias: tuple[str, ...]
) -> bool:
    """Cuenta el uso de una capacidad aunque runtime la nombre por id o slug."""
    alias = {str(referencia).casefold() for referencia in referencias if referencia}
    if not alias:
        return False
    ahora = time.time()
    with db._conn() as c:
        filas = c.execute(
            "SELECT id, referencia FROM perfil_capacidades WHERE user_id=? AND tipo=?",
            (user_id, tipo),
        ).fetchall()
        ids = [fila["id"] for fila in filas if str(fila["referencia"]).casefold() in alias]
        if not ids:
            return False
        c.executemany(
            "UPDATE perfil_capacidades SET usos=usos+1, ultimo_uso=? WHERE id=?",
            [(ahora, capacidad_id) for capacidad_id in ids],
        )
    return True


def fijar_nivel(user_id: str, tipo: str, referencia: str, nivel: str) -> None:
    if nivel not in NIVELES:
        raise PerfilInvalido(f"«{nivel}» no es un nivel; son {', '.join(NIVELES)}")
    with db._conn() as c:
        c.execute(
            "UPDATE perfil_capacidades SET nivel=? WHERE user_id=? AND tipo=? AND referencia=?",
            (nivel, user_id, tipo, referencia),
        )


def fijar_nivel_por_id(user_id: str, capacidad_id: int, nivel: str) -> bool:
    if nivel not in NIVELES:
        raise PerfilInvalido(f"«{nivel}» no es un nivel; son {', '.join(NIVELES)}")
    with db._conn() as c:
        cursor = c.execute(
            "UPDATE perfil_capacidades SET nivel=? WHERE id=? AND user_id=?",
            (nivel, capacidad_id, user_id),
        )
        return cursor.rowcount > 0


def eliminar_afirmacion(user_id: str, afirmacion_id: int) -> bool:
    with db._conn() as c:
        cursor = c.execute(
            "DELETE FROM perfil_afirmaciones WHERE id=? AND user_id=?",
            (afirmacion_id, user_id),
        )
        return cursor.rowcount > 0


def eliminar_capacidad(user_id: str, capacidad_id: int) -> bool:
    with db._conn() as c:
        fila = c.execute(
            "SELECT tipo, referencia FROM perfil_capacidades WHERE id=? AND user_id=?",
            (capacidad_id, user_id),
        ).fetchone()
        if fila:
            c.execute(
                """INSERT OR IGNORE INTO perfil_capacidades_retiradas
                   (user_id, tipo, referencia) VALUES (?, ?, ?)""",
                (user_id, fila["tipo"], fila["referencia"]),
            )
        cursor = c.execute(
            "DELETE FROM perfil_capacidades WHERE id=? AND user_id=?",
            (capacidad_id, user_id),
        )
        return cursor.rowcount > 0


def borrar_perfil(user_id: str) -> None:
    with db._conn() as c:
        c.execute(
            """INSERT OR IGNORE INTO perfil_capacidades_retiradas
               (user_id, tipo, referencia)
               SELECT user_id, tipo, referencia FROM perfil_capacidades
               WHERE user_id=?""",
            (user_id,),
        )
        c.execute("DELETE FROM perfil WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM perfil_afirmaciones WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM perfil_capacidades WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM perfil_propuestas WHERE user_id=?", (user_id,))


def guardar_resumen(user_id: str, resumen: str) -> None:
    ahora = time.time()
    with db._conn() as c:
        c.execute(
            """INSERT INTO perfil (user_id, resumen, creado_en, revisado_en)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   resumen = excluded.resumen,
                   revisado_en = excluded.revisado_en""",
            (user_id, resumen.strip(), ahora, ahora),
        )


def resumen_de(user_id: str) -> str:
    from . import perfil_activador  # noqa: PLC0415
    conf = perfil_activador.decidir(afirmaciones_de(user_id), capacidades_de(user_id))
    return conf.resumen


def mcp_retirados_de(user_id: str) -> tuple[str, ...]:
    with db._conn() as c:
        return tuple(
            str(fila["referencia"])
            for fila in c.execute(
                """SELECT referencia FROM perfil_capacidades_retiradas
                   WHERE user_id=? AND tipo='mcp'""",
                (user_id,),
            )
        )


def capacidades_retiradas_de(user_id: str, tipo: str) -> tuple[str, ...]:
    with db._conn() as c:
        return tuple(
            str(fila["referencia"])
            for fila in c.execute(
                """SELECT referencia FROM perfil_capacidades_retiradas
                   WHERE user_id=? AND tipo=?""",
                (user_id, tipo),
            )
        )


def registrar_propuestas(user_id: str, propuestas: list[dict]) -> None:
    ahora = time.time()
    with db._conn() as c:
        for propuesta in propuestas:
            c.execute(
                """INSERT INTO perfil_propuestas
                   (user_id, tipo, referencia, bloque, estado, propuesta_en, decidida_en)
                   VALUES (?, ?, ?, ?, 'pendiente', ?, NULL)
                   ON CONFLICT(user_id, tipo, referencia) DO UPDATE SET
                       bloque=excluded.bloque,
                       estado='pendiente',
                       propuesta_en=excluded.propuesta_en,
                       decidida_en=NULL""",
                (
                    user_id,
                    propuesta["tipo"],
                    propuesta["referencia"],
                    propuesta["bloque"],
                    ahora,
                ),
            )


def resolver_propuestas(user_id: str, aprobadas: set[tuple[str, str]]) -> None:
    ahora = time.time()
    with db._conn() as c:
        _resolver_propuestas(c, user_id, aprobadas, ahora)


def _resolver_propuestas(c, user_id: str, aprobadas: set[tuple[str, str]], ahora: float) -> None:
    pendientes = c.execute(
        """SELECT id, tipo, referencia FROM perfil_propuestas
           WHERE user_id=? AND estado='pendiente'""",
        (user_id,),
    ).fetchall()
    c.executemany(
        "UPDATE perfil_propuestas SET estado=?, decidida_en=? WHERE id=?",
        [
            (
                "aprobada" if (fila["tipo"], fila["referencia"]) in aprobadas else "rechazada",
                ahora,
                fila["id"],
            )
            for fila in pendientes
        ],
    )


def metricas_propuestas(user_id: str) -> tuple[int, int]:
    with db._conn() as c:
        fila = c.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN estado='aprobada' THEN 1 ELSE 0 END) AS aprobadas
               FROM perfil_propuestas WHERE user_id=? AND estado!='pendiente'""",
            (user_id,),
        ).fetchone()
    return int(fila["total"] or 0), int(fila["aprobadas"] or 0)


def guardar_entrevista(
    user_id: str,
    afirmaciones: list[dict],
    capacidades: list[dict],
) -> None:
    """Valida todo primero y aplica la entrevista en una sola transacción."""
    afirmaciones_limpias = []
    for afirmacion in afirmaciones:
        clase = afirmacion.get("clase", "")
        procedencia = afirmacion.get("procedencia") or "entrevista"
        valor = _normalizar(afirmacion.get("valor"))
        if clase not in CLASES or procedencia not in PROCEDENCIAS or not valor:
            raise PerfilInvalido("La entrevista contiene una afirmación no válida")
        # Marcar una hipótesis confirmada como entrevista evita conservarla al 0,4.
        if procedencia == "inventario":
            procedencia = "entrevista"
        afirmaciones_limpias.append((clase, valor, procedencia))

    capacidades_limpias = []
    for capacidad in capacidades:
        tipo = capacidad.get("tipo", "")
        referencia = str(capacidad.get("referencia") or "").strip()
        justificacion = str(capacidad.get("justificacion") or "").strip()
        transporte = str(capacidad.get("transporte") or "")
        endpoint = str(capacidad.get("endpoint") or "").strip()
        if tipo not in TIPOS or not referencia or not justificacion:
            raise PerfilInvalido("La entrevista contiene una capacidad no válida")
        if tipo == "mcp":
            if transporte != "remoto":
                raise PerfilInvalido("Solo se pueden activar MCP remotos verificados")
            parsed = urlparse(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise PerfilInvalido("Un MCP remoto necesita un endpoint HTTP válido")
        capacidades_limpias.append(
            (tipo, referencia, justificacion, transporte, endpoint)
        )

    ahora = time.time()
    with db._conn() as c:
        _asegurar_perfil(c, user_id, ahora)
        for clase, valor, procedencia in afirmaciones_limpias:
            inicial = CONFIANZA_INICIAL[procedencia]
            c.execute(
                """INSERT INTO perfil_afirmaciones
                   (user_id, clase, valor, procedencia, confianza, creada_en, movida_en)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, clase, valor) DO UPDATE SET
                       procedencia=CASE WHEN excluded.confianza > confianza
                                       THEN excluded.procedencia ELSE procedencia END,
                       confianza=MAX(confianza, excluded.confianza),
                       movida_en=CASE WHEN excluded.confianza > confianza
                                     THEN excluded.movida_en ELSE movida_en END""",
                (user_id, clase, valor, procedencia, inicial, ahora, ahora),
            )
        for tipo, referencia, motivo, transporte, endpoint in capacidades_limpias:
            c.execute(
                """INSERT INTO perfil_capacidades
                   (user_id, tipo, referencia, justificacion, transporte, nivel, aprobada_en, endpoint)
                   VALUES (?, ?, ?, ?, ?, 'completo', ?, ?)
                   ON CONFLICT(user_id, tipo, referencia) DO UPDATE SET
                       justificacion=excluded.justificacion,
                       transporte=excluded.transporte,
                       nivel='completo',
                       aprobada_en=excluded.aprobada_en,
                       endpoint=excluded.endpoint""",
                (user_id, tipo, referencia, motivo, transporte, ahora, endpoint),
            )
            c.execute(
                """DELETE FROM perfil_capacidades_retiradas
                   WHERE user_id=? AND tipo=? AND referencia=?""",
                (user_id, tipo, referencia),
            )
        _resolver_propuestas(
            c,
            user_id,
            {(tipo, referencia) for tipo, referencia, *_ in capacidades_limpias},
            ahora,
        )


def marcar_revisado(user_id: str, ahora: float | None = None) -> None:
    momento = ahora if ahora is not None else time.time()
    with db._conn() as c:
        _asegurar_perfil(c, user_id, momento)
        c.execute("UPDATE perfil SET revisado_en=? WHERE user_id=?", (momento, user_id))


def ultima_revision(user_id: str) -> float | None:
    with db._conn() as c:
        fila = c.execute("SELECT revisado_en FROM perfil WHERE user_id=?", (user_id,)).fetchone()
    return float(fila["revisado_en"]) if fila else None


def usuarios_con_perfil() -> tuple[str, ...]:
    with db._conn() as c:
        return tuple(str(fila["user_id"]) for fila in c.execute("SELECT user_id FROM perfil"))


def aplicar_capacidades(user: dict) -> None:
    """Sincroniza skills y vigilancias gestionadas por el perfil."""
    from . import perfil_activador, skills, vigilancias  # noqa: PLC0415

    capacidades = capacidades_de(user["id"])
    configuracion = perfil_activador.decidir(
        afirmaciones_de(user["id"]), capacidades
    )
    completas = set(configuracion.skills_completas)
    gestionadas = {
        capacidad["referencia"]
        for capacidad in capacidades
        if capacidad["tipo"] == "skill"
    }
    gestionadas.update(capacidades_retiradas_de(user["id"], "skill"))
    visibles = skills.list_visible(user)
    for skill in visibles:
        referencias = {str(skill["id"]), str(skill["slug"])}
        if not referencias.intersection(gestionadas):
            continue
        habilitada = bool(referencias.intersection(completas))
        if bool(skill["enabled"]) != habilitada:
            skills.set_enabled(user, skill["id"], habilitada)

    vigilancias.fijar_activas_del_perfil(
        user["id"],
        set(configuracion.vigilancias_activas),
        {
            capacidad["referencia"]
            for capacidad in capacidades
            if capacidad["tipo"] == "vigilancia"
        }.union(capacidades_retiradas_de(user["id"], "vigilancia")),
    )

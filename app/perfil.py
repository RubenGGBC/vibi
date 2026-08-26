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

from . import db

CLASES = frozenset({"dominio", "herramienta", "preferencia", "aficion"})
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
        """)


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

"""Mirar lo que el usuario hace de verdad, y ajustar lo que se creía.

**Aquí no piensa nadie: se cuenta.** Es el mismo reparto que en `avisos.py` y
`vigilancias.py`, y por el mismo motivo: la parte tonta sale gratis y puede
correr siempre, y el modelo entra una vez por revisión —cuatro llamadas al
mes— en vez de una vez por evento. Un heartbeat de cinco minutos costaría 288
llamadas diarias haya pasado algo o no.

**Y no lee el disco.** Mirar los archivos del usuario pertenece a la
entrevista, con su escalada y su permiso. Aquí solo se leen contadores que ya
están en la base: ningún dato nuevo sale hacia el modelo.

## Límites

- `herramientas_usadas` y `capacidades_sin_usar` filtran por `user_id`, pero
  `apps_con_receta` es global: la tabla `recetas` no tiene `user_id`.
- `desde` solo se aplica a `tool_invocations` (eventos del periodo). Las otras
  dos señales son estado actual.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import db


@dataclass(frozen=True)
class Senales:
    herramientas_usadas: dict[str, int]
    apps_con_receta: tuple[str, ...]
    capacidades_sin_usar: tuple[tuple[str, str], ...]


def leer_senales(user_id: str, desde: float) -> Senales:
    """Todo lo observable desde ese momento, en una sola pasada."""
    with db._conn() as c:
        usadas: dict[str, int] = {}
        for fila in c.execute(
            """SELECT tool_id, COUNT(*) AS veces FROM tool_invocations
               WHERE actor_user_id = ? AND requested_at >= ?
               GROUP BY tool_id""",
            (user_id, desde),
        ):
            usadas[str(fila["tool_id"])] = int(fila["veces"])

        apps: tuple[str, ...] = tuple(
            str(f["app"])
            for f in c.execute("SELECT app FROM recetas ORDER BY app")
        )

        sin_usar = tuple(
            (str(f["tipo"]), str(f["referencia"]))
            for f in c.execute(
                """SELECT tipo, referencia FROM perfil_capacidades
                   WHERE user_id=? AND usos = 0""",
                (user_id,),
            )
        )

    return Senales(
        herramientas_usadas=usadas,
        apps_con_receta=apps,
        capacidades_sin_usar=sin_usar,
    )

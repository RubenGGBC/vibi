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

- `herramientas_usadas` y las capacidades filtran por `user_id`, pero
  `apps_con_receta` es global: la tabla `recetas` no tiene `user_id`.
- `desde` delimita todas las señales. Una capacidad aprobada dentro del periodo
  no decae hasta la siguiente revisión completa.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass

from . import db, perfil

log = logging.getLogger("vibi.perfil_observador")

SEMANA = 7 * 86_400
INVOCACIONES_PARA_REVISAR = 50
INTERVALO_WORKER = 3600.0


@dataclass(frozen=True)
class Senales:
    herramientas_usadas: dict[str, int]
    apps_con_receta: tuple[str, ...]
    capacidades_sin_usar: tuple[tuple[str, str], ...]
    capacidades_usadas: tuple[tuple[str, str], ...] = ()


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
            for f in c.execute(
                "SELECT app FROM recetas WHERE creada_en >= ? ORDER BY app",
                (desde,),
            )
        )

        sin_usar = tuple(
            (str(f["tipo"]), str(f["referencia"]))
            for f in c.execute(
                """SELECT tipo, referencia FROM perfil_capacidades
                   WHERE user_id=?
                     AND (? <= 0 OR aprobada_en < ?)
                     AND (ultimo_uso IS NULL OR ultimo_uso < ?)""",
                (user_id, desde, desde, desde),
            )
        )
        usadas_cap = tuple(
            (str(f["tipo"]), str(f["referencia"]))
            for f in c.execute(
                """SELECT tipo, referencia FROM perfil_capacidades
                   WHERE user_id=? AND ultimo_uso >= ?""",
                (user_id, desde),
            )
        )

    return Senales(
        herramientas_usadas=usadas,
        apps_con_receta=apps,
        capacidades_sin_usar=sin_usar,
        capacidades_usadas=usadas_cap,
    )


def _palabras(texto: str) -> list[str]:
    """Las palabras de un nombre, en minúsculas y sin separadores."""
    return [p for p in re.split(r"[^0-9a-záéíóúñü]+", str(texto).casefold()) if p]


def revisar(user_id: str, senales: Senales) -> dict:
    """Mueve las confianzas y devuelve qué ha cambiado.

    Mover confianzas es aritmética y no necesita modelo. El modelo entra
    después y solo para redactar la propuesta que se le enseña al usuario.

    Cuando lo observado contradice lo declarado en la entrevista, gana lo
    observado: lo que alguien hace pesa más que lo que dijo que haría.
    """
    afirmaciones = perfil.afirmaciones_de(user_id)
    capacidades = perfil.capacidades_de(user_id)
    apoyos: set[tuple[str, str]] = set()
    for herramienta in senales.herramientas_usadas:
        clave = herramienta.casefold()
        apoyos.update(
            (afirmacion["clase"], afirmacion["valor"])
            for afirmacion in afirmaciones
            if afirmacion["valor"] in clave
        )
    for app in senales.apps_con_receta:
        # Palabra completa y no subcadena: si no, una receta de «wordpress»
        # apoyaría la afirmación «word», y el apoyo vale 0,10 en un sistema
        # donde nada más sube la confianza sola.
        palabras = set(_palabras(app))
        for afirmacion in afirmaciones:
            if afirmacion["clase"] != "herramienta":
                continue
            if set(_palabras(afirmacion["valor"])).intersection(palabras):
                apoyos.add(("herramienta", afirmacion["valor"]))

    por_clave = {
        (capacidad["tipo"], capacidad["referencia"]): capacidad
        for capacidad in capacidades
    }

    def relacionadas(capacidad: dict) -> list[tuple[str, str]]:
        motivo = capacidad["justificacion"].casefold()
        return [
            (afirmacion["clase"], afirmacion["valor"])
            for afirmacion in afirmaciones
            if afirmacion["valor"] in motivo
        ]

    for clave in senales.capacidades_usadas:
        capacidad = por_clave.get(clave)
        if not capacidad:
            continue
        apoyos.update(relacionadas(capacidad))
        perfil.fijar_nivel(user_id, clave[0], clave[1], "completo")

    for clase, valor in sorted(apoyos):
        perfil.apoyar(user_id, clase, valor)
    apoyadas = [valor for _clase, valor in sorted(apoyos)]

    decaidas: list[str] = []
    propuestas: list[str] = []
    relaciones_por_capacidad: dict[tuple[str, str], list[tuple[str, str]]] = {}
    desuso_por_capacidad: dict[tuple[str, str], int] = {}
    a_decaer: set[tuple[str, str]] = set()
    for tipo, referencia in senales.capacidades_sin_usar:
        capacidad = por_clave.get((tipo, referencia))
        if not capacidad:
            continue
        vinculadas = relacionadas(capacidad)
        relaciones_por_capacidad[(tipo, referencia)] = vinculadas
        desuso_por_capacidad[(tipo, referencia)] = perfil.anotar_desuso(
            user_id, tipo, referencia
        )
        a_decaer.update(vinculadas)
        decaidas.append(referencia)

    # Una afirmación pierde como máximo 0,05 por revisión, aunque sostenga
    # varios servidores distintos.
    perfil.decaer(user_id, sin_uso=sorted(a_decaer))
    actuales = {
        (afirmacion["clase"], afirmacion["valor"]): afirmacion["confianza"]
        for afirmacion in perfil.afirmaciones_de(user_id)
    }
    for (tipo, referencia), vinculadas in relaciones_por_capacidad.items():
        confianzas = [
            actuales[clave] for clave in vinculadas if clave in actuales
        ]
        # El desuso manda siempre; la confianza solo puede empeorar el
        # veredicto, nunca salvarlo. Sin ninguna afirmación que la sostenga
        # —el caso normal, porque la justificación viene en inglés del
        # registro— la capacidad no se da por muerta: baja de escalón.
        nivel = perfil.nivel_por_desuso(desuso_por_capacidad[(tipo, referencia)])
        if confianzas:
            nivel = perfil.peor_nivel(nivel, perfil.nivel_para(min(confianzas)))
        perfil.fijar_nivel(user_id, tipo, referencia, nivel)
        if nivel == "propuesta_retirada":
            propuestas.append(referencia)

    return {
        "apoyadas": apoyadas,
        "decaidas": decaidas,
        "propuestas_retirada": propuestas,
    }


def debe_revisar(user_id: str, ahora: float | None = None) -> tuple[bool, float]:
    momento = ahora if ahora is not None else time.time()
    desde = perfil.ultima_revision(user_id)
    if desde is None:
        return False, momento
    if momento - desde >= SEMANA:
        return True, desde
    with db._conn() as c:
        fila = c.execute(
            """SELECT COUNT(*) AS total FROM tool_invocations
               WHERE actor_user_id=? AND requested_at >= ?""",
            (user_id, desde),
        ).fetchone()
    return int(fila["total"] or 0) >= INVOCACIONES_PARA_REVISAR, desde


async def worker() -> None:
    """Revisa perfiles vencidos sin hacer una llamada al modelo por evento."""
    while True:
        try:
            for user_id in perfil.usuarios_con_perfil():
                toca, desde = debe_revisar(user_id)
                if not toca:
                    continue
                resultado = revisar(user_id, leer_senales(user_id, desde))
                perfil.marcar_revisado(user_id)
                user = db.get_user_by_id(user_id)
                if user:
                    from .executors import antigravity_chat  # noqa: PLC0415
                    await antigravity_chat.aplicar_perfil(user)
                log.info("Perfil revisado automáticamente para %s: %s", user_id, resultado)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - una revisión no mata el worker
            log.warning("No se pudo completar la revisión automática: %s", error)
        await asyncio.sleep(INTERVALO_WORKER)

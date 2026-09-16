"""De señales observadas a estado de equipo e intervenciones."""
from __future__ import annotations

import asyncio
import time

from . import avisos, equipo, presencia
from .equipo_iniciativa import Candidata, elegir


CADUCIDAD = 24 * 3600.0

_MAPA = {
    "avance": ("estado", "en_progreso", 0.80, "en_progreso"),
    "entregado": ("estado", "entregado", 0.90, "entregada"),
    "revision_pendiente": ("estado", "esperando_revision", 0.85, "esperando_revision"),
    "sin_avance": ("bloqueo", "posible", 0.45, None),
    "fallo_repetido": ("bloqueo", "probable", 0.80, None),
    "tarea_larga": ("bloqueo", "posible", 0.55, None),
    "integracion_rota": ("bloqueo", "integracion", 0.90, None),
}

_INICIATIVAS = {
    "sin_avance": (45, "No he visto avance en la tarea durante el intervalo aprobado. ¿Necesitas desbloquear algo?"),
    "fallo_repetido": (90, "El mismo trabajo ha fallado varias veces. ¿Quieres que busquemos a alguien que conozca esta parte?"),
    "tarea_larga": (60, "El trabajo lleva bastante más de lo previsto. ¿Quieres que revise contigo si sigue avanzando?"),
    "revision_pendiente": (55, "La tarea parece estar esperando una revisión. ¿Quieres que avise a quien corresponda?"),
    "integracion_rota": (100, "La integración del equipo está fallando. Te lo cuento una vez para que podáis decidir quién la mira."),
}


def reducir(senal: dict) -> dict | None:
    """Aplica una señal ya autenticada. No llama a modelos ni toca la red."""
    regla = _MAPA.get(senal["nombre"])
    if not regla:
        return None
    clase, valor, confianza, estado_tarea = regla
    # Conservamos la hora observada en el log, pero un reloj local adelantado
    # no puede fabricar una creencia que tarde semanas en caducar.
    vista = min(float(senal["observada_en"]), float(senal["recibida_en"]) + 300)
    creencia = equipo.creer(
        equipo_id=senal["equipo_id"],
        tarea_id=senal["tarea_id"],
        user_id=senal["user_id"],
        clave=f"tarea:{senal['tarea_id']}:{clase}",
        clase=clase,
        valor=valor,
        procedencia="observacion",
        confianza=confianza,
        vista_en=vista,
        caduca_en=vista + CADUCIDAD,
        senal_id=senal["id"],
    )
    if estado_tarea:
        equipo.cambiar_estado_tarea(senal["tarea_id"], estado_tarea, vista)
    iniciativa = _INICIATIVAS.get(senal["nombre"])
    if iniciativa:
        prioridad, texto = iniciativa
        # La misma clase sobre la misma tarea no forma una cola infinita.
        equipo.encolar_iniciativa(
            senal["equipo_id"], senal["tarea_id"], senal["user_id"],
            senal["nombre"], texto, prioridad,
            f"{senal['tarea_id']}:{senal['nombre']}",
        )
    return creencia


async def despachar_pendientes() -> int:
    pendientes = equipo.iniciativas_pendientes()
    por_usuario: dict[str, list[dict]] = {}
    for candidata in pendientes:
        por_usuario.setdefault(candidata["destinatario"], []).append(candidata)
    entregadas = 0
    for user_id, filas in por_usuario.items():
        ids = elegir(
            [
                Candidata(
                    f["id"], f["prioridad"], f["creada_en"],
                    f["clase"] == "integracion_rota",
                )
                for f in filas
            ],
            gastadas=equipo.gastadas_hoy(user_id),
            libre=presencia.libre(user_id),
        )
        por_id = {f["id"]: f for f in filas}
        for iniciativa_id in ids:
            fila = por_id[iniciativa_id]
            # Entra en la cola que ya respeta conversación, silencios y turno
            # de agy. El modelo del equipo solo aparece aquí, una vez por
            # cambio que sobrevivió a presupuesto y presencia.
            await avisos.recibir(
                user_id,
                {
                    "app": "Coordinación de equipo",
                    "titulo": "El trabajo del equipo ha cambiado",
                    "cuerpo": fila["texto"],
                },
            )
            equipo.marcar_iniciativa(iniciativa_id, "entregada")
            entregadas += 1
    return entregadas


async def worker(interval_seconds: float = 5.0) -> None:
    while True:
        try:
            await despachar_pendientes()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Una candidata rara no puede matar la cola del resto.
            import logging
            logging.getLogger("vibi.equipo").exception("Fallo en iniciativa de equipo")
        await asyncio.sleep(interval_seconds)

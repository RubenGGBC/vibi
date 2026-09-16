"""Priorización pura de la iniciativa del coordinador."""
from __future__ import annotations

from dataclasses import dataclass


PRESUPUESTO_DIARIO = 4


@dataclass(frozen=True)
class Candidata:
    id: int
    prioridad: int
    creada_en: float
    fuera_presupuesto: bool = False


def elegir(
    candidatas: list[Candidata],
    *,
    gastadas: int,
    libre: bool,
    presupuesto: int = PRESUPUESTO_DIARIO,
) -> list[int]:
    """Devuelve qué candidatas salen ahora, sin tocar reloj, red ni base."""
    if not libre:
        return []
    ordenadas = sorted(candidatas, key=lambda c: (-c.prioridad, c.creada_en, c.id))
    urgentes = [c.id for c in ordenadas if c.fuera_presupuesto]
    quedan = max(0, presupuesto - max(0, gastadas))
    personales = [c.id for c in ordenadas if not c.fuera_presupuesto]
    return urgentes + personales[:quedan]

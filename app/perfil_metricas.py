"""Los números con los que se defiende que esto sirve para algo.

Dos métricas, y la segunda es la que no reporta nadie del área. Skilldex puntúa
si el `SKILL.md` tiene el frontmatter bien puesto y sus propios autores aclaran
que eso «explicitly is not a measure of functional quality». Medir si la
capacidad instalada seguía usándose dos semanas después sí lo es.
"""
from __future__ import annotations

import time

from . import perfil


DIA = 86_400


def tasa_de_aceptacion(propuestas: int, aprobadas: int) -> float:
    """Qué proporción de lo propuesto le pareció bien al usuario."""
    if propuestas <= 0:
        return 0.0
    return aprobadas / propuestas


def supervivencia(user_id: str, dias: int, ahora: float | None = None) -> float:
    """De lo aprobado hace más de ``dias``, cuánto se sigue usando.

    Las aprobadas hace menos del plazo no cuentan en el denominador: no han
    tenido tiempo de demostrar nada, y meterlas hundiría la métrica por una
    razón que no tiene que ver con acertar.
    """
    momento = ahora if ahora is not None else time.time()
    limite = momento - dias * DIA
    maduras = [
        capacidad
        for capacidad in perfil.capacidades_de(user_id)
        if capacidad["aprobada_en"] is not None and capacidad["aprobada_en"] <= limite
    ]
    if not maduras:
        return 0.0
    vivas = [capacidad for capacidad in maduras if (capacidad["usos"] or 0) > 0]
    return len(vivas) / len(maduras)

"""Constructor local del vocabulario cerrado de coordinación."""
from __future__ import annotations

import time
import uuid


SENALES = frozenset({
    "avance", "sin_avance", "entregado", "fallo_repetido", "tarea_larga",
    "revision_pendiente", "integracion_rota", "competencia", "disponible",
})

SONDA_POR_SENAL = {
    "avance": "archivo",
    "sin_avance": "archivo",
    "entregado": "archivo",
    "fallo_repetido": "proceso",
    "tarea_larga": "proceso",
    "revision_pendiente": "web",
    "integracion_rota": "web",
}

PAYLOADS = {
    "avance": frozenset(),
    "sin_avance": frozenset({"horas"}),
    "entregado": frozenset(),
    "fallo_repetido": frozenset({"veces"}),
    "tarea_larga": frozenset({"minutos"}),
    "revision_pendiente": frozenset(),
    "integracion_rota": frozenset(),
}


def construir(
    seguimiento: str, senal: str, secuencia: int, payload: dict | None = None,
    *, observada_en: float | None = None,
) -> dict:
    """Crea un sobre sin aceptar claves que puedan transportar contenido."""
    if senal not in PAYLOADS:
        raise ValueError("Señal de nodo desconocida")
    datos = payload or {}
    if set(datos) != PAYLOADS[senal]:
        raise ValueError("Payload fuera del vocabulario de la señal")
    return {
        "tipo": "senal_equipo",
        "id": str(uuid.uuid4()),
        "seguimiento": seguimiento,
        "secuencia": int(secuencia),
        "senal": senal,
        "payload": datos,
        "observada_en": time.time() if observada_en is None else observada_en,
        "schema": 1,
    }


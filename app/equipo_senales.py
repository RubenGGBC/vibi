"""Contrato cerrado de las señales que un nodo puede publicar al equipo.

Este módulo no interpreta trabajo ni texto. Su única responsabilidad es dejar
pasar mensajes con una forma conocida y pequeña. La relación con equipo,
tarea, usuario y nodo se obtiene después desde ``seguimiento``; confiar esos
campos al emisor permitiría que un nodo hablase por otro.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


SENALES = frozenset({
    "avance",
    "sin_avance",
    "entregado",
    "fallo_repetido",
    "tarea_larga",
    "revision_pendiente",
    "integracion_rota",
    "competencia",
    "disponible",
})

_CAMPOS_PAYLOAD: dict[str, dict[str, type]] = {
    "avance": {},
    "sin_avance": {"horas": float},
    "entregado": {},
    "fallo_repetido": {"veces": int},
    "tarea_larga": {"minutos": float},
    "revision_pendiente": {},
    "integracion_rota": {},
    "competencia": {"area": str, "confianza": float},
    "disponible": {},
}

_CAMPOS_MENSAJE = {
    "tipo", "id", "seguimiento", "secuencia", "senal", "payload",
    "observada_en", "schema",
}

# Si una futura señal intenta introducir alguno de estos conceptos, falla antes
# de alcanzar la base. No sustituye al allowlist exacto, pero hace explícita la
# propiedad que la prueba de no fuga protege.
CAMPOS_PROHIBIDOS = frozenset({
    "contenido", "texto", "detalle", "antes", "ahora", "ruta", "url",
    "archivo", "nombre_archivo", "ventana", "titulo", "comando", "salida",
    "teclas", "captura",
})


class SenalInvalida(ValueError):
    """El nodo envió algo fuera del contrato de equipo."""


@dataclass(frozen=True)
class Senal:
    id: str
    seguimiento: str
    secuencia: int
    nombre: str
    payload: dict
    observada_en: float
    schema: int = 1


def _numero(valor: object, nombre: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise SenalInvalida(f"{nombre} tiene que ser un número")
    numero = float(valor)
    if not math.isfinite(numero) or numero < 0:
        raise SenalInvalida(f"{nombre} tiene que ser finito y no negativo")
    return numero


def validar_payload(nombre: str, crudo: object) -> dict:
    if nombre not in SENALES:
        raise SenalInvalida(f"Señal desconocida: {nombre}")
    if not isinstance(crudo, dict):
        raise SenalInvalida("payload tiene que ser un objeto")
    esperados = _CAMPOS_PAYLOAD[nombre]
    sobra = set(crudo) - set(esperados)
    falta = set(esperados) - set(crudo)
    if sobra or falta:
        partes = []
        if sobra:
            partes.append(f"sobran {', '.join(sorted(sobra))}")
        if falta:
            partes.append(f"faltan {', '.join(sorted(falta))}")
        raise SenalInvalida("Payload inválido: " + "; ".join(partes))
    if set(crudo).intersection(CAMPOS_PROHIBIDOS):
        raise SenalInvalida("La señal intenta transportar contenido prohibido")

    limpio: dict = {}
    for campo, tipo in esperados.items():
        valor = crudo[campo]
        if tipo in (int, float):
            numero = _numero(valor, campo)
            limpio[campo] = int(numero) if tipo is int else numero
        elif tipo is str:
            if not isinstance(valor, str):
                raise SenalInvalida(f"{campo} tiene que ser texto")
            texto = " ".join(valor.split())
            if not texto or len(texto) > 80:
                raise SenalInvalida(f"{campo} tiene una longitud inválida")
            limpio[campo] = texto.casefold()
    if nombre == "competencia" and limpio["confianza"] > 1:
        raise SenalInvalida("confianza tiene que estar entre 0 y 1")
    return limpio


def validar(crudo: object) -> Senal:
    if not isinstance(crudo, dict):
        raise SenalInvalida("La señal tiene que ser un objeto")
    sobra = set(crudo) - _CAMPOS_MENSAJE
    falta = _CAMPOS_MENSAJE - set(crudo)
    if sobra or falta:
        raise SenalInvalida("El sobre de señal no coincide con el esquema v1")
    if crudo.get("tipo") != "senal_equipo" or crudo.get("schema") != 1:
        raise SenalInvalida("Tipo o versión de señal desconocidos")
    identificador = str(crudo.get("id") or "")
    seguimiento = str(crudo.get("seguimiento") or "")
    nombre = str(crudo.get("senal") or "")
    if not identificador or len(identificador) > 64:
        raise SenalInvalida("id de señal inválido")
    if not seguimiento or len(seguimiento) > 64:
        raise SenalInvalida("seguimiento inválido")
    secuencia = crudo.get("secuencia")
    if isinstance(secuencia, bool) or not isinstance(secuencia, int) or secuencia < 1:
        raise SenalInvalida("secuencia inválida")
    observada = _numero(crudo.get("observada_en"), "observada_en")
    return Senal(
        id=identificador,
        seguimiento=seguimiento,
        secuencia=secuencia,
        nombre=nombre,
        payload=validar_payload(nombre, crudo.get("payload")),
        observada_en=observada,
    )


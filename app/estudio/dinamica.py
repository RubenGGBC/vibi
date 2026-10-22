"""Sistemas dinámicos cualesquiera: las ecuaciones las escribe el agente.

Un péndulo, una órbita, Lorenz o depredador-presa son el mismo objeto: un
vector de estado y sus derivadas. En vez de programar cada caso, el agente
declara variables, valores iniciales y ecuaciones (`omega' = -g/L*sin(theta)`)
y el engine las integra con RK4.

Aquí se integra un tramo en el servidor para validar y para contarle al agente
qué hace de verdad su sistema (rangos, periodo, si diverge) antes de que lo
explique. El cliente integra la misma forma canónica en vivo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .expresiones import Expresion

DT = 1 / 240
LIMITE = 1e9


@dataclass(frozen=True)
class Sistema:
    orden: tuple[str, ...]
    iniciales: dict[str, float]
    derivadas: dict[str, Expresion]


def _derivar(sistema: Sistema, estado: dict[str, float], t: float, valores: dict) -> dict:
    entorno = {**valores, **estado, "t": t}
    return {v: sistema.derivadas[v].evaluar(entorno) for v in sistema.orden}


def _rk4(sistema: Sistema, estado: dict[str, float], t: float, h: float, valores: dict) -> dict:
    def mas(a: dict, k: dict, f: float) -> dict:
        return {v: a[v] + f * k[v] for v in sistema.orden}

    k1 = _derivar(sistema, estado, t, valores)
    k2 = _derivar(sistema, mas(estado, k1, h / 2), t + h / 2, valores)
    k3 = _derivar(sistema, mas(estado, k2, h / 2), t + h / 2, valores)
    k4 = _derivar(sistema, mas(estado, k3, h), t + h, valores)
    return {
        v: estado[v] + h / 6 * (k1[v] + 2 * k2[v] + 2 * k3[v] + k4[v])
        for v in sistema.orden
    }


def _oscilacion(serie: list[tuple[float, float]], variable: str) -> dict:
    """Si la variable oscila con regularidad, cada cuánto y cómo es su amplitud.

    Solo se habla de **periodo** si los intervalos entre cruces y la amplitud se
    mantienen: un sistema amortiguado o uno caótico que gira un rato en un
    lóbulo también cruza a intervalos regulares, y llamarlo periodo engañaría.
    """
    if len(serie) < 3:
        return {}
    media = sum(v for _, v in serie) / len(serie)
    if max(v for _, v in serie) - min(v for _, v in serie) < 1e-9:
        return {}
    indices = [
        i + 1 for i, ((_, v0), (_, v1)) in enumerate(zip(serie, serie[1:]))
        if v0 < media <= v1
    ]
    # Tres cruces son dos ciclos completos: lo mínimo para comparar.
    if len(indices) < 3:
        return {}
    cruces = [serie[i][0] for i in indices]
    intervalos = [b - a for a, b in zip(cruces, cruces[1:])]
    media_intervalo = sum(intervalos) / len(intervalos)
    if max(abs(i - media_intervalo) for i in intervalos) > 0.05 * media_intervalo:
        return {f"{variable}_oscila": "de forma irregular (sin periodo)"}
    picos = [max(v for _, v in serie[a:b]) - media for a, b in zip(indices, indices[1:])]
    primero, ultimo = picos[0], picos[-1]
    if primero > 0 and abs(ultimo - primero) <= 0.05 * primero:
        return {f"periodo_de_{variable}_s": _redondear(media_intervalo)}
    tendencia = "crece" if ultimo > primero else "decrece"
    return {
        f"{variable}_oscila_cada_s": _redondear(media_intervalo),
        f"amplitud_de_{variable}": f"{tendencia} (de {_redondear(primero)} a {_redondear(ultimo)}): no es un periodo estable",
    }


def integrar(sistema: Sistema, valores: dict[str, float], segundos: float = 30.0) -> dict:
    """Integra y resume. No devuelve la trayectoria: devuelve lo que se cuenta."""
    estado = dict(sistema.iniciales)
    t = 0.0
    pasos = int(segundos / DT)
    muestras = {1.0, 5.0, 10.0, segundos}
    instantaneas = [{"t": 0.0, **{v: _redondear(x) for v, x in estado.items()}}]
    minimos = dict(estado)
    maximos = dict(estado)
    serie: list[tuple[float, float]] = []
    primera = sistema.orden[0]
    for paso in range(1, pasos + 1):
        estado = _rk4(sistema, estado, t, DT, valores)
        t = paso * DT
        malos = [v for v, x in estado.items() if not math.isfinite(x) or abs(x) > LIMITE]
        if malos:
            return {
                "estable": False,
                "diverge_en_t": round(t, 3),
                "variables_que_explotan": malos,
                "instantaneas": instantaneas,
                "aviso": "El sistema diverge o deja de existir: revisa signos, "
                "unidades o valores iniciales",
            }
        for v, x in estado.items():
            minimos[v] = min(minimos[v], x)
            maximos[v] = max(maximos[v], x)
        if paso % 4 == 0:
            serie.append((t, estado[primera]))
        if any(abs(t - m) < DT / 2 for m in muestras):
            instantaneas.append({"t": round(t, 3), **{v: _redondear(x) for v, x in estado.items()}})
    resumen = {
        "estable": True,
        "segundos_simulados": segundos,
        "instantaneas": instantaneas,
        "rangos": {v: [_redondear(minimos[v]), _redondear(maximos[v])] for v in sistema.orden},
    }
    resumen.update(_oscilacion(serie, primera))
    return resumen


def _redondear(x: float) -> float:
    return float(f"{x:.6g}")

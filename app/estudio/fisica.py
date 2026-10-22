"""Los modelos físicos que el engine sabe simular, y lo que se sabe de ellos.

El cliente integra la ecuación de cada modelo fotograma a fotograma. Aquí se
declara qué parámetros tiene cada uno, con qué unidades y entre qué límites, y
se calculan las magnitudes que el modelo va a querer contar: el periodo de un
péndulo, el alcance de un proyectil. Esos números salen de la fórmula cerrada
(o de la integral elíptica, en el péndulo de amplitud grande), no de lo que
recuerde el modelo de lenguaje.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


class SimulacionInvalida(ValueError):
    pass


@dataclass(frozen=True)
class Parametro:
    nombre: str
    unidad: str
    minimo: float
    maximo: float
    defecto: float
    descripcion: str


@dataclass(frozen=True)
class Modelo:
    id: str
    nombre: str
    ecuacion: str
    parametros: tuple[Parametro, ...]


MODELOS: dict[str, Modelo] = {
    "pendulo": Modelo(
        "pendulo",
        "Péndulo simple",
        "θ'' = −(g/L)·sin θ − c·θ'",
        (
            Parametro("longitud", "m", 0.1, 20, 1, "Longitud del hilo"),
            Parametro("gravedad", "m/s²", 0.5, 30, 9.81, "Aceleración de la gravedad"),
            Parametro("angulo_inicial", "°", 1, 179, 30, "Ángulo desde el que se suelta"),
            Parametro("amortiguamiento", "1/s", 0, 2, 0, "Rozamiento (0 = ideal)"),
        ),
    ),
    "muelle": Modelo(
        "muelle",
        "Masa y muelle",
        "m·x'' = −k·x − c·x'",
        (
            Parametro("masa", "kg", 0.1, 50, 1, "Masa colgada"),
            Parametro("rigidez", "N/m", 0.1, 500, 10, "Constante del muelle k"),
            Parametro("amplitud", "m", 0.05, 2, 0.5, "Desplazamiento inicial"),
            Parametro("amortiguamiento", "kg/s", 0, 20, 0, "Coeficiente c"),
        ),
    ),
    "proyectil": Modelo(
        "proyectil",
        "Tiro parabólico",
        "x = v₀·cos α·t;  y = h₀ + v₀·sin α·t − ½·g·t²",
        (
            Parametro("velocidad", "m/s", 1, 200, 20, "Velocidad de salida"),
            Parametro("angulo", "°", 0, 90, 45, "Ángulo de tiro"),
            Parametro("gravedad", "m/s²", 0.5, 30, 9.81, "Aceleración de la gravedad"),
            Parametro("altura_inicial", "m", 0, 100, 0, "Altura de lanzamiento"),
        ),
    ),
    "onda": Modelo(
        "onda",
        "Onda viajera",
        "y(x, t) = A·sin(k·x − ω·t)",
        (
            Parametro("amplitud", "m", 0.05, 3, 1, "Amplitud A"),
            Parametro("longitud_onda", "m", 0.2, 20, 4, "Longitud de onda λ"),
            Parametro("frecuencia", "Hz", 0.05, 5, 0.5, "Frecuencia f"),
        ),
    ),
}


def _agm(a: float, b: float) -> float:
    """Media aritmético-geométrica: converge en cuatro o cinco vueltas."""
    for _ in range(40):
        a, b = (a + b) / 2, math.sqrt(a * b)
        if abs(a - b) < 1e-15 * a:
            break
    return a


def integral_eliptica_k(k: float) -> float:
    """K(k) = π / (2·AGM(1, √(1−k²)))."""
    return math.pi / (2 * _agm(1.0, math.sqrt(1 - k * k)))


def _r(valor: float, cifras: int = 4) -> float:
    if valor == 0 or not math.isfinite(valor):
        return valor
    return round(valor, cifras - 1 - int(math.floor(math.log10(abs(valor)))))


def resolver_parametros(
    modelo: Modelo, dados: dict[str, float]
) -> dict[str, float]:
    """Completa con los valores por defecto y comprueba unidades y límites."""
    validos = {parametro.nombre: parametro for parametro in modelo.parametros}
    sobrantes = set(dados) - set(validos)
    if sobrantes:
        raise SimulacionInvalida(
            f"{modelo.nombre} no tiene {', '.join(sorted(sobrantes))}. "
            f"Sus parámetros: {', '.join(validos)}"
        )
    valores: dict[str, float] = {}
    for nombre, parametro in validos.items():
        valor = float(dados.get(nombre, parametro.defecto))
        if not parametro.minimo <= valor <= parametro.maximo:
            raise SimulacionInvalida(
                f"{nombre} = {valor} {parametro.unidad} está fuera de "
                f"[{parametro.minimo}, {parametro.maximo}]"
            )
        valores[nombre] = valor
    return valores


def magnitudes(modelo_id: str, p: dict[str, float]) -> dict[str, object]:
    """Lo que se puede afirmar de esta simulación, calculado."""
    if modelo_id == "pendulo":
        longitud, g = p["longitud"], p["gravedad"]
        theta0 = math.radians(p["angulo_inicial"])
        aproximado = 2 * math.pi * math.sqrt(longitud / g)
        exacto = 4 * math.sqrt(longitud / g) * integral_eliptica_k(math.sin(theta0 / 2))
        datos: dict[str, object] = {
            "periodo_pequenas_oscilaciones_s": _r(aproximado),
            "periodo_real_s": _r(exacto),
            "error_de_la_aproximacion_pct": _r((exacto - aproximado) / exacto * 100, 3),
            "velocidad_maxima_m_s": _r(math.sqrt(2 * g * longitud * (1 - math.cos(theta0)))),
        }
        if p["amortiguamiento"] > 0:
            datos["nota"] = (
                "Con amortiguamiento la amplitud decae; los periodos son los "
                "del péndulo ideal"
            )
        return datos
    if modelo_id == "muelle":
        m, k, c, a = p["masa"], p["rigidez"], p["amortiguamiento"], p["amplitud"]
        omega0 = math.sqrt(k / m)
        zeta = c / (2 * math.sqrt(k * m))
        if zeta == 0:
            regimen = "sin amortiguamiento (oscila para siempre)"
        elif zeta < 1:
            regimen = "subamortiguado (oscila y se va apagando)"
        elif zeta == 1:
            regimen = "amortiguamiento crítico (vuelve sin oscilar, lo más rápido posible)"
        else:
            regimen = "sobreamortiguado (vuelve despacio sin oscilar)"
        datos = {
            "frecuencia_angular_rad_s": _r(omega0),
            "periodo_s": _r(2 * math.pi / omega0),
            "factor_de_amortiguamiento": _r(zeta, 3),
            "regimen": regimen,
            "energia_inicial_J": _r(0.5 * k * a * a),
        }
        if 0 < zeta < 1:
            datos["periodo_amortiguado_s"] = _r(2 * math.pi / (omega0 * math.sqrt(1 - zeta**2)))
        return datos
    if modelo_id == "proyectil":
        v, g, h = p["velocidad"], p["gravedad"], p["altura_inicial"]
        alfa = math.radians(p["angulo"])
        vx, vy = v * math.cos(alfa), v * math.sin(alfa)
        tiempo = (vy + math.sqrt(vy * vy + 2 * g * h)) / g
        return {
            "tiempo_de_vuelo_s": _r(tiempo),
            "alcance_m": _r(vx * tiempo),
            "altura_maxima_m": _r(h + vy * vy / (2 * g)),
            "angulo_de_maximo_alcance_deg": (
                45 if h == 0 else _r(math.degrees(math.atan(v / math.sqrt(v * v + 2 * g * h))))
            ),
        }
    if modelo_id == "onda":
        a, lam, f = p["amplitud"], p["longitud_onda"], p["frecuencia"]
        return {
            "velocidad_de_propagacion_m_s": _r(lam * f),
            "numero_de_onda_rad_m": _r(2 * math.pi / lam),
            "frecuencia_angular_rad_s": _r(2 * math.pi * f),
            "periodo_s": _r(1 / f),
            "amplitud_m": a,
        }
    raise SimulacionInvalida(f"Modelo desconocido: {modelo_id}")

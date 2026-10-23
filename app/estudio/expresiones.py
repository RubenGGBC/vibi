"""Fórmulas sin `eval`: un lenguaje pequeño, cerrado y el mismo en los dos lados.

El modelo escribe `1/n`, `sin(a*x)` o `x^2 + y^2`. Aquí se analiza con el
parser de Python, se recorre el árbol y se rechaza todo lo que no esté en la
lista: no hay atributos, ni índices, ni lambdas, ni nombres que no se hayan
declarado. Lo que pasa el filtro se evalúa recorriendo ese mismo árbol con
`float`, nunca con `eval`, y nunca con enteros de Python: `10^10^10` con
enteros dejaría al servidor calculando un número de diez mil millones de
cifras; con `float` es un desbordamiento que se convierte en `nan`.

El cliente evalúa las mismas fórmulas con mathjs para que mover un deslizador
no tenga que ir y volver del servidor. Por eso la forma que se guarda en la
escena es la **canónica** que devuelve `compilar`: reconstruida desde el árbol
y con `^` para la potencia, que es lo que entiende mathjs. Las funciones de
`FUNCIONES` existen con el mismo nombre y el mismo significado en los dos
lados (`ln` se registra en el cliente como alias de `log`).
"""
from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Callable

MAX_LONGITUD = 300
MAX_NODOS = 200


class ExpresionInvalida(ValueError):
    """La fórmula no se puede usar. El mensaje es para el modelo: dice qué
    cambiar, no solo que algo falló."""


def _redondear(x: float) -> float:
    # mathjs redondea alejándose del cero; `round` de Python, al par. Que
    # coincidan importa más que cuál de los dos es mejor.
    return math.copysign(math.floor(abs(x) + 0.5), x)


def _factorial(x: float) -> float:
    if x < 0 and float(x).is_integer():
        return math.nan
    return math.gamma(x + 1)


def _log(x: float, base: float | None = None) -> float:
    return math.log(x) if base is None else math.log(x, base)


def _signo(x: float) -> float:
    return (x > 0) - (x < 0)


def _mod(a: float, b: float) -> float:
    # mathjs: el resultado tiene el signo del divisor, como el `%` de Python.
    return math.fmod(a, b) if b == 0 else a - b * math.floor(a / b)


# nombre → (función, aridad mínima, aridad máxima)
FUNCIONES: dict[str, tuple[Callable[..., float], int, int]] = {
    "sin": (math.sin, 1, 1),
    "cos": (math.cos, 1, 1),
    "tan": (math.tan, 1, 1),
    "asin": (math.asin, 1, 1),
    "acos": (math.acos, 1, 1),
    "atan": (math.atan, 1, 1),
    "atan2": (math.atan2, 2, 2),
    "sinh": (math.sinh, 1, 1),
    "cosh": (math.cosh, 1, 1),
    "tanh": (math.tanh, 1, 1),
    "exp": (math.exp, 1, 1),
    "log": (_log, 1, 2),
    "ln": (math.log, 1, 1),
    "log10": (math.log10, 1, 1),
    "log2": (math.log2, 1, 1),
    "sqrt": (math.sqrt, 1, 1),
    "cbrt": (lambda x: math.copysign(abs(x) ** (1 / 3), x), 1, 1),
    "abs": (abs, 1, 1),
    "floor": (math.floor, 1, 1),
    "ceil": (math.ceil, 1, 1),
    "round": (_redondear, 1, 1),
    "sign": (_signo, 1, 1),
    "min": (min, 1, 8),
    "max": (max, 1, 8),
    "mod": (_mod, 2, 2),
    "factorial": (_factorial, 1, 1),
    "gamma": (math.gamma, 1, 1),
}

CONSTANTES: dict[str, float] = {"pi": math.pi, "e": math.e}

_BINARIOS: dict[type, Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a ** b,
}
_UNARIOS: dict[type, Callable[[float], float]] = {
    ast.USub: lambda a: -a,
    ast.UAdd: lambda a: a,
}


@dataclass(frozen=True)
class Expresion:
    """Una fórmula ya validada."""

    fuente: str
    variables: frozenset[str]
    _arbol: ast.expr

    def evaluar(self, entorno: dict[str, float]) -> float:
        """Su valor, o `nan` si en ese punto no existe (fuera del dominio,
        división por cero, desbordamiento)."""
        try:
            valor = _evaluar(self._arbol, entorno)
        except (ArithmeticError, ValueError, TypeError):
            return math.nan
        if isinstance(valor, complex):
            # `(-8)**(1/3)` en Python es complejo; en mathjs también deja de
            # ser real. Para pintar, no existe.
            return math.nan
        return float(valor)


def _evaluar(nodo: ast.expr, entorno: dict[str, float]) -> float:
    if isinstance(nodo, ast.Constant):
        return float(nodo.value)
    if isinstance(nodo, ast.Name):
        if nodo.id in entorno:
            return float(entorno[nodo.id])
        return CONSTANTES[nodo.id]
    if isinstance(nodo, ast.BinOp):
        return _BINARIOS[type(nodo.op)](
            _evaluar(nodo.left, entorno), _evaluar(nodo.right, entorno)
        )
    if isinstance(nodo, ast.UnaryOp):
        return _UNARIOS[type(nodo.op)](_evaluar(nodo.operand, entorno))
    if isinstance(nodo, ast.Call):
        funcion = FUNCIONES[nodo.func.id][0]  # type: ignore[attr-defined]
        return float(funcion(*(_evaluar(arg, entorno) for arg in nodo.args)))
    raise TypeError(type(nodo).__name__)


def compilar(texto: str, permitidas: set[str] | frozenset[str]) -> Expresion:
    """Valida la fórmula y la devuelve lista para evaluar.

    `permitidas` son los nombres libres que puede usar: la variable del
    elemento (`x`, `n`…) y los deslizadores de la escena.
    """
    texto = (texto or "").strip()
    if not texto:
        raise ExpresionInvalida("La expresión está vacía")
    if len(texto) > MAX_LONGITUD:
        raise ExpresionInvalida(
            f"La expresión pasa de {MAX_LONGITUD} caracteres; divídela"
        )
    try:
        arbol = ast.parse(texto.replace("^", "**"), mode="eval").body
    except SyntaxError as error:
        raise ExpresionInvalida(
            f"No se entiende «{texto}»: escribe los productos con * (2*x, no "
            "2x) y la potencia con ^"
        ) from error

    usadas: set[str] = set()
    # El nombre de una llamada (`sin` en `sin(x)`) también es un `ast.Name`;
    # se mira en su propio caso, no como variable.
    nombres_de_llamada = {
        id(nodo.func) for nodo in ast.walk(arbol) if isinstance(nodo, ast.Call)
    }
    nodos = 0
    for nodo in ast.walk(arbol):
        nodos += 1
        if nodos > MAX_NODOS:
            raise ExpresionInvalida("La expresión es demasiado larga")
        if id(nodo) in nombres_de_llamada:
            continue
        if isinstance(nodo, (ast.operator, ast.unaryop, ast.Load)):
            if isinstance(nodo, ast.operator) and type(nodo) not in _BINARIOS:
                raise ExpresionInvalida(
                    "Solo valen + - * / ^; para el resto usa mod(a, b)"
                )
            if isinstance(nodo, ast.unaryop) and type(nodo) not in _UNARIOS:
                raise ExpresionInvalida("Operador no permitido")
            continue
        if isinstance(nodo, ast.Constant):
            if isinstance(nodo.value, bool) or not isinstance(
                nodo.value, (int, float)
            ):
                raise ExpresionInvalida("Solo valen números")
            continue
        if isinstance(nodo, ast.Name):
            if nodo.id in FUNCIONES and nodo.id not in permitidas:
                raise ExpresionInvalida(
                    f"«{nodo.id}» es una función: escribe {nodo.id}(...)"
                )
            if nodo.id not in permitidas and nodo.id not in CONSTANTES:
                disponibles = ", ".join(sorted(permitidas)) or "ninguna"
                raise ExpresionInvalida(
                    f"«{nodo.id}» no existe en esta escena. Variables "
                    f"disponibles: {disponibles}. Si es un deslizador, créalo "
                    "antes con estudio_parametro"
                )
            if nodo.id in permitidas:
                usadas.add(nodo.id)
            continue
        if isinstance(nodo, ast.Call):
            nombre = nodo.func.id if isinstance(nodo.func, ast.Name) else ""
            if nombre not in FUNCIONES:
                raise ExpresionInvalida(
                    f"Función desconocida «{ast.unparse(nodo.func)}». "
                    f"Disponibles: {', '.join(sorted(FUNCIONES))}"
                )
            if nodo.keywords:
                raise ExpresionInvalida(f"{nombre} no admite argumentos con nombre")
            minimo, maximo = FUNCIONES[nombre][1:]
            if not minimo <= len(nodo.args) <= maximo:
                raise ExpresionInvalida(
                    f"{nombre} recibe {minimo}"
                    + (f"–{maximo}" if maximo != minimo else "")
                    + " argumento(s)"
                )
            continue
        if isinstance(nodo, (ast.BinOp, ast.UnaryOp)):
            continue
        raise ExpresionInvalida(
            f"«{ast.unparse(nodo)}» no está permitido en una fórmula"
        )

    fuente = ast.unparse(arbol).replace("**", "^")
    return Expresion(fuente=fuente, variables=frozenset(usadas), _arbol=arbol)


def es_finito(valor: float) -> bool:
    return not (math.isnan(valor) or math.isinf(valor))

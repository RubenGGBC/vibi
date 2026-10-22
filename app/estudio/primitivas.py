"""Las herramientas del engine, tal y como las ve el modelo.

Se registran en `tools.PRIMITIVES`, así que llegan a los dos motores por el
mismo camino que todas las demás (el MCP interno de Claude y el puente MCP de
`agy`) y pasan por la misma validación y auditoría.

Cada herramienta hace tres cosas: valida con mensajes que dicen qué corregir,
calcula con el engine (nunca con lo que el modelo crea saber) y devuelve los
números que el modelo va a necesitar para explicar lo que se ve.
"""
from __future__ import annotations

import base64
import math
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .. import events
from ..tools import EmptyArguments, Primitive, ToolError, ToolExecutionFailed
from . import algoritmos, capturas, escena as esc, fisica, modelos, moleculas
from .expresiones import ExpresionInvalida, compilar, es_finito

Rango = list[float]
Numero = float | str

PERMISOS = ("estudio:write:self",)
EFECTOS = ("estudio:escena",)
SOLO_LECTURA = ("estudio:read:self",)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _rango(valor: list[float] | None, nombre: str) -> list[float] | None:
    if valor is None:
        return None
    if len(valor) != 2 or not all(math.isfinite(v) for v in valor):
        raise esc.EscenaError(f"{nombre} tiene que ser [mínimo, máximo]")
    if valor[0] >= valor[1]:
        raise esc.EscenaError(f"En {nombre} el mínimo tiene que ser menor que el máximo")
    return [float(valor[0]), float(valor[1])]


def _r(valor: float) -> float | None:
    if not es_finito(valor):
        return None
    return float(f"{valor:.6g}")


def _fallo(error: Exception) -> ToolExecutionFailed:
    return ToolExecutionFailed(str(error))


ERRORES_DEL_MODELO = (
    esc.EscenaError,
    ExpresionInvalida,
    fisica.SimulacionInvalida,
    algoritmos.AlgoritmoInvalido,
)


def _procedencia(origen: str, detalle: str, **extra) -> dict:
    return {"origen": origen, "detalle": detalle, **extra}


# --- Escena -------------------------------------------------------------------


class NuevaEscenaArgs(_Args):
    titulo: str = Field(min_length=1, max_length=120)
    modo: Literal["2d", "3d"] = "2d"
    rango_x: Rango | None = None
    rango_y: Rango | None = None
    rango_z: Rango | None = None
    ejes: bool = True


async def _nueva_escena(user: dict, a: NuevaEscenaArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            version = escena.get("version", 0)
            escena.clear()
            escena.update(esc.escena_vacia())
            escena["version"] = version
            escena["titulo"] = a.titulo.strip()
            escena["modo"] = a.modo
            ejes = escena["ejes"]
            ejes["visibles"] = a.ejes
            if a.modo == "3d":
                ejes["x"], ejes["y"], ejes["z"] = [-4.0, 4.0], [-4.0, 4.0], [-3.0, 3.0]
            for eje in ("x", "y", "z"):
                rango = _rango(getattr(a, f"rango_{eje}"), f"rango_{eje}")
                if rango:
                    ejes[eje] = rango
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {
        "escena": a.titulo,
        "modo": a.modo,
        "ejes": escena["ejes"],
        "siguiente": "Añade deslizadores y elementos; después, los pasos",
    }


class EjesArgs(_Args):
    rango_x: Rango | None = None
    rango_y: Rango | None = None
    rango_z: Rango | None = None
    visibles: bool | None = None


async def _ejes(user: dict, a: EjesArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            for eje in ("x", "y", "z"):
                rango = _rango(getattr(a, f"rango_{eje}"), f"rango_{eje}")
                if rango:
                    escena["ejes"][eje] = rango
            if a.visibles is not None:
                escena["ejes"]["visibles"] = a.visibles
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {"ejes": escena["ejes"]}


class ParametroArgs(_Args):
    id: str = Field(min_length=1, max_length=32)
    etiqueta: str = Field(min_length=1, max_length=60)
    minimo: float
    maximo: float
    valor: float
    paso: float | None = Field(default=None, gt=0)


async def _parametro(user: dict, a: ParametroArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            esc.validar_id_parametro(escena, a.id)
            if a.minimo >= a.maximo:
                raise esc.EscenaError("El mínimo tiene que ser menor que el máximo")
            if not a.minimo <= a.valor <= a.maximo:
                raise esc.EscenaError("El valor inicial tiene que estar entre mínimo y máximo")
            paso = a.paso or (
                1.0
                if all(float(v).is_integer() for v in (a.minimo, a.maximo))
                and a.maximo - a.minimo <= 1000
                else (a.maximo - a.minimo) / 100
            )
            nuevo = {
                "id": a.id,
                "etiqueta": a.etiqueta.strip(),
                "minimo": a.minimo,
                "maximo": a.maximo,
                "paso": paso,
                "valor": a.valor,
            }
            existentes = escena["parametros"]
            for i, p in enumerate(existentes):
                if p["id"] == a.id:
                    existentes[i] = nuevo
                    break
            else:
                if len(existentes) >= esc.MAX_PARAMETROS:
                    raise esc.EscenaError(f"Como mucho {esc.MAX_PARAMETROS} deslizadores")
                existentes.append(nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {
        "deslizador": nuevo,
        "uso": f"Escribe «{a.id}» dentro de las expresiones o como valor de "
        "un parámetro de simulación",
    }


# --- Matemáticas ----------------------------------------------------------------


def _muestrear(expresion, variable: str, a: float, b: float, valores: dict, n: int = 400):
    xs = [a + (b - a) * i / (n - 1) for i in range(n)]
    ys = [expresion.evaluar({**valores, variable: x}) for x in xs]
    return xs, ys


def _avisos_de_rango(ys: list[float], rango: list[float], eje: str) -> list[str]:
    finitos = [y for y in ys if es_finito(y)]
    avisos = []
    if len(finitos) < len(ys) * 0.5:
        avisos.append(
            "Más de la mitad de los puntos no existen (fuera del dominio o "
            "infinitos): revisa la expresión o el dominio"
        )
    if finitos:
        dentro = [y for y in finitos if rango[0] <= y <= rango[1]]
        if len(dentro) < len(finitos) * 0.6:
            avisos.append(
                f"Buena parte se sale del eje {eje} {rango}; valores entre "
                f"{_r(min(finitos))} y {_r(max(finitos))}. Ajusta con estudio_ejes"
            )
    return avisos


class FuncionArgs(_Args):
    expresion: str = Field(min_length=1, max_length=300)
    id: str | None = None
    etiqueta: str | None = Field(default=None, max_length=80)
    color: str | None = None
    variable: Literal["x", "t"] = "x"
    desde: float | None = None
    hasta: float | None = None


async def _funcion(user: dict, a: FuncionArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            permitidas = {a.variable} | esc.ids_de_parametros(escena)
            expresion = compilar(a.expresion, permitidas)
            ejes = escena["ejes"]
            dominio = None
            if a.desde is not None or a.hasta is not None:
                dominio = _rango(
                    [
                        a.desde if a.desde is not None else ejes["x"][0],
                        a.hasta if a.hasta is not None else ejes["x"][1],
                    ],
                    "el dominio",
                )
            inicio, fin = dominio or ejes["x"]
            valores = esc.valores_parametros(escena)
            xs, ys = _muestrear(expresion, a.variable, inicio, fin, valores)
            eje_vertical = "z" if escena["modo"] == "3d" else "y"
            avisos = _avisos_de_rango(ys, ejes[eje_vertical], eje_vertical)
            elemento_id = esc.resolver_id(escena, "funcion", a.id)
            nuevo = {
                "id": elemento_id,
                "tipo": "funcion",
                "expresion": expresion.fuente,
                "variable": a.variable,
                "dominio": dominio,
                "usa": sorted(expresion.variables - {a.variable}),
                "etiqueta": a.etiqueta or f"f({a.variable}) = {expresion.fuente}",
                "color": esc.resolver_color(escena, a.color),
                "procedencia": _procedencia(
                    "engine", f"Evaluada por el engine: {expresion.fuente}"
                ),
            }
            sustituida = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    finitos = [y for y in ys if es_finito(y)]
    muestras = [
        {a.variable: _r(xs[i]), "valor": _r(ys[i])}
        for i in range(0, len(xs), (len(xs) - 1) // 4)
    ]
    return {
        "id": elemento_id,
        "sustituida": sustituida,
        "expresion": expresion.fuente,
        "valores_con_deslizadores": valores,
        "muestras": muestras,
        "rango_observado": [_r(min(finitos)), _r(max(finitos))] if finitos else None,
        "avisos": avisos,
    }


class SucesionArgs(_Args):
    expresion: str = Field(min_length=1, max_length=300)
    desde: int = Field(default=1, ge=0, le=10_000)
    hasta: int | str = Field(
        default=20,
        description="Último índice: un número o el id de un deslizador",
    )
    estilo: Literal["barras", "puntos", "linea"] = "barras"
    acumulada: bool = Field(
        default=False,
        description="True pinta las sumas parciales S_k = a_desde + … + a_k",
    )
    id: str | None = None
    etiqueta: str | None = Field(default=None, max_length=80)
    color: str | None = None


MAX_TERMINOS = 2000


async def _sucesion(user: dict, a: SucesionArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            parametros = {p["id"]: p for p in escena["parametros"]}
            expresion = compilar(a.expresion, {"n"} | set(parametros))
            if isinstance(a.hasta, str):
                if a.hasta not in parametros:
                    raise esc.EscenaError(
                        f"hasta = «{a.hasta}» no es un número ni un deslizador"
                    )
                if parametros[a.hasta]["maximo"] - a.desde > MAX_TERMINOS:
                    raise esc.EscenaError(
                        f"El deslizador {a.hasta} permite más de {MAX_TERMINOS} términos"
                    )
                ultimo = int(parametros[a.hasta]["valor"])
            else:
                if a.hasta - a.desde > MAX_TERMINOS:
                    raise esc.EscenaError(f"Como mucho {MAX_TERMINOS} términos")
                ultimo = a.hasta
            if ultimo < a.desde:
                raise esc.EscenaError("hasta tiene que ser mayor o igual que desde")
            valores = esc.valores_parametros(escena)
            terminos = [
                expresion.evaluar({**valores, "n": float(n)})
                for n in range(a.desde, ultimo + 1)
            ]
            sumas, total = [], 0.0
            for termino in terminos:
                total += termino
                sumas.append(total)
            serie = sumas if a.acumulada else terminos
            elemento_id = esc.resolver_id(escena, "sucesion", a.id)
            usa = sorted(expresion.variables - {"n"})
            if isinstance(a.hasta, str):
                usa = sorted(set(usa) | {a.hasta})
            nuevo = {
                "id": elemento_id,
                "tipo": "sucesion",
                "expresion": expresion.fuente,
                "desde": a.desde,
                "hasta": a.hasta,
                "estilo": a.estilo,
                "acumulada": a.acumulada,
                "usa": usa,
                "etiqueta": a.etiqueta
                or (f"S_k = Σ {expresion.fuente}" if a.acumulada else f"a_n = {expresion.fuente}"),
                "color": esc.resolver_color(escena, a.color),
                "procedencia": _procedencia(
                    "engine", f"Términos calculados por el engine: {expresion.fuente}"
                ),
            }
            eje_vertical = "z" if escena["modo"] == "3d" else "y"
            avisos = _avisos_de_rango(serie, escena["ejes"][eje_vertical], eje_vertical)
            if not (escena["ejes"]["x"][0] <= a.desde and ultimo <= escena["ejes"]["x"][1]):
                avisos.append(
                    f"Los índices {a.desde}…{ultimo} no caben en el eje x "
                    f"{escena['ejes']['x']}; ajústalo con estudio_ejes"
                )
            sustituida = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {
        "id": elemento_id,
        "sustituida": sustituida,
        "expresion": expresion.fuente,
        "indices": [a.desde, ultimo],
        "primeros_terminos": [_r(t) for t in terminos[:6]],
        "ultimo_termino": _r(terminos[-1]),
        "suma_parcial_hasta_el_ultimo": _r(sumas[-1]),
        "primeras_sumas_parciales": [_r(s) for s in sumas[:6]],
        "avisos": avisos,
    }


class SuperficieArgs(_Args):
    expresion: str = Field(min_length=1, max_length=300, description="z = f(x, y)")
    id: str | None = None
    etiqueta: str | None = Field(default=None, max_length=80)
    resolucion: int = Field(default=48, ge=10, le=90)


async def _superficie(user: dict, a: SuperficieArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            if escena["modo"] != "3d":
                raise esc.EscenaError(
                    "Las superficies necesitan una escena 3d: "
                    "estudio_nueva_escena(modo='3d')"
                )
            expresion = compilar(a.expresion, {"x", "y"} | esc.ids_de_parametros(escena))
            ejes, valores = escena["ejes"], esc.valores_parametros(escena)
            pasos = 24
            zs = [
                expresion.evaluar(
                    {
                        **valores,
                        "x": ejes["x"][0] + (ejes["x"][1] - ejes["x"][0]) * i / pasos,
                        "y": ejes["y"][0] + (ejes["y"][1] - ejes["y"][0]) * j / pasos,
                    }
                )
                for i in range(pasos + 1)
                for j in range(pasos + 1)
            ]
            avisos = _avisos_de_rango(zs, ejes["z"], "z")
            elemento_id = esc.resolver_id(escena, "superficie", a.id)
            nuevo = {
                "id": elemento_id,
                "tipo": "superficie",
                "expresion": expresion.fuente,
                "resolucion": a.resolucion,
                "usa": sorted(expresion.variables - {"x", "y"}),
                "etiqueta": a.etiqueta or f"z = {expresion.fuente}",
                "color": esc.resolver_color(escena, None),
                "procedencia": _procedencia(
                    "engine", f"Evaluada por el engine: z = {expresion.fuente}"
                ),
            }
            sustituida = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    finitos = [z for z in zs if es_finito(z)]
    return {
        "id": elemento_id,
        "sustituida": sustituida,
        "expresion": expresion.fuente,
        "z_observado": [_r(min(finitos)), _r(max(finitos))] if finitos else None,
        "avisos": avisos,
    }


class MarcaArgs(_Args):
    tipo: Literal["punto", "vector", "etiqueta"]
    posicion: list[Numero] = Field(
        min_length=2, max_length=3,
        description="[x, y] o [x, y, z]; cada coordenada puede ser una expresión con deslizadores",
    )
    desde: list[Numero] | None = Field(
        default=None, min_length=2, max_length=3, description="Origen del vector (por defecto, el origen)"
    )
    texto: str | None = Field(default=None, max_length=160)
    id: str | None = None
    color: str | None = None


async def _marca(user: dict, a: MarcaArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            parametros = esc.ids_de_parametros(escena)
            valores = esc.valores_parametros(escena)
            usa: set[str] = set()

            def coordenadas(lista: list[Numero]) -> tuple[list[str], list[float | None]]:
                fuentes, actuales = [], []
                for coordenada in list(lista) + [0] * (3 - len(lista)):
                    expresion = compilar(str(coordenada), parametros)
                    usa.update(expresion.variables)
                    fuentes.append(expresion.fuente)
                    actuales.append(_r(expresion.evaluar(valores)))
                return fuentes, actuales

            posicion, en = coordenadas(a.posicion)
            nuevo = {
                "id": esc.resolver_id(escena, a.tipo, a.id),
                "tipo": a.tipo,
                "posicion": posicion,
                "color": esc.resolver_color(escena, a.color),
            }
            if a.tipo == "vector":
                origen, desde = coordenadas(a.desde or [0, 0, 0])
                nuevo["desde"] = origen
            if a.tipo == "etiqueta":
                if not a.texto:
                    raise esc.EscenaError("Una etiqueta necesita texto")
                nuevo["etiqueta"] = a.texto
                nuevo["procedencia"] = _procedencia("modelo", "Texto redactado por el modelo")
            else:
                nuevo["etiqueta"] = a.texto or ""
                nuevo["procedencia"] = _procedencia("engine", "Coordenadas evaluadas por el engine")
            nuevo["usa"] = sorted(usa)
            sustituida = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    resultado = {"id": nuevo["id"], "sustituida": sustituida, "posicion_actual": en}
    if a.tipo == "vector":
        resultado["desde_actual"] = desde
        diferencia = [
            (f - i) if f is not None and i is not None else None for f, i in zip(en, desde)
        ]
        if None not in diferencia:
            resultado["modulo"] = _r(math.sqrt(sum(d * d for d in diferencia)))
    return resultado


# --- Física -------------------------------------------------------------------


class SimulacionArgs(_Args):
    modelo: Literal["pendulo", "muelle", "proyectil", "onda"]
    parametros: dict[str, Numero] = Field(
        default_factory=dict,
        description="Valor de cada parámetro (número) o id de un deslizador que lo controle",
    )
    id: str | None = None
    etiqueta: str | None = Field(default=None, max_length=80)


def _descripcion_modelos() -> str:
    return "; ".join(
        f"{m.id}: "
        + ", ".join(
            f"{p.nombre} [{p.unidad}] {p.minimo}–{p.maximo} (def. {p.defecto})"
            for p in m.parametros
        )
        for m in fisica.MODELOS.values()
    )


async def _simulacion(user: dict, a: SimulacionArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            modelo = fisica.MODELOS[a.modelo]
            limites = {p.nombre: p for p in modelo.parametros}
            deslizadores = {p["id"]: p for p in escena["parametros"]}
            numericos: dict[str, float] = {}
            usa = []
            for nombre, valor in a.parametros.items():
                if isinstance(valor, str):
                    if valor not in deslizadores:
                        raise esc.EscenaError(
                            f"{nombre} = «{valor}» no es un número ni un deslizador"
                        )
                    deslizador = deslizadores[valor]
                    limite = limites.get(nombre)
                    if limite and (
                        deslizador["minimo"] < limite.minimo
                        or deslizador["maximo"] > limite.maximo
                    ):
                        raise esc.EscenaError(
                            f"El deslizador {valor} va de {deslizador['minimo']} a "
                            f"{deslizador['maximo']}, pero {nombre} solo admite "
                            f"{limite.minimo}–{limite.maximo} {limite.unidad}"
                        )
                    numericos[nombre] = float(deslizador["valor"])
                    usa.append(valor)
                else:
                    numericos[nombre] = float(valor)
            resueltos = fisica.resolver_parametros(modelo, numericos)
            datos = fisica.magnitudes(a.modelo, resueltos)
            elemento_id = esc.resolver_id(escena, "simulacion", a.id)
            nuevo = {
                "id": elemento_id,
                "tipo": "simulacion",
                "modelo": a.modelo,
                "parametros": {
                    nombre: a.parametros.get(nombre, resueltos[nombre])
                    for nombre in resueltos
                },
                "unidades": {p.nombre: p.unidad for p in modelo.parametros},
                "ecuacion": modelo.ecuacion,
                "usa": sorted(usa),
                "etiqueta": a.etiqueta or modelo.nombre,
                "color": esc.resolver_color(escena, None),
                "procedencia": _procedencia(
                    "engine", f"Integrada por el engine: {modelo.ecuacion}"
                ),
            }
            sustituida = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    resultado = {
        "id": elemento_id,
        "sustituida": sustituida,
        "modelo": modelo.nombre,
        "ecuacion": modelo.ecuacion,
        "parametros": resueltos,
        "magnitudes_calculadas": datos,
    }
    if usa:
        resultado["nota"] = (
            "Hay parámetros en deslizadores: las magnitudes son para sus "
            "valores actuales y cambian cuando el alumno los mueve"
        )
    return resultado


# --- Algoritmos -----------------------------------------------------------------


class NodoArg(_Args):
    id: str = Field(min_length=1, max_length=24)
    etiqueta: str | None = Field(default=None, max_length=40)


class AristaArg(_Args):
    desde: str
    hasta: str
    peso: float = 1.0


class GrafoArgs(_Args):
    nodos: list[str | NodoArg] = Field(min_length=1, max_length=algoritmos.MAX_NODOS)
    aristas: list[AristaArg] = Field(default_factory=list, max_length=algoritmos.MAX_ARISTAS)
    dirigido: bool = False
    id: str | None = None
    etiqueta: str | None = Field(default=None, max_length=80)


async def _grafo(user: dict, a: GrafoArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            nodos = [
                {"id": n, "etiqueta": n} if isinstance(n, str)
                else {"id": n.id, "etiqueta": n.etiqueta or n.id}
                for n in a.nodos
            ]
            ids = [n["id"] for n in nodos]
            if len(set(ids)) != len(ids):
                raise esc.EscenaError("Hay nodos repetidos")
            for arista in a.aristas:
                for extremo in (arista.desde, arista.hasta):
                    if extremo not in ids:
                        raise esc.EscenaError(f"La arista usa «{extremo}», que no es un nodo")
                if not math.isfinite(arista.peso):
                    raise esc.EscenaError("Los pesos tienen que ser números finitos")
            posiciones = algoritmos.disposicion_circular(ids)
            for nodo in nodos:
                nodo["posicion"] = posiciones[nodo["id"]]
            elemento_id = esc.resolver_id(escena, "grafo", a.id)
            nuevo = {
                "id": elemento_id,
                "tipo": "grafo",
                "nodos": nodos,
                "aristas": [arista.model_dump() for arista in a.aristas],
                "dirigido": a.dirigido,
                "recorrido": None,
                "usa": [],
                "etiqueta": a.etiqueta or "Grafo",
                "color": esc.resolver_color(escena, None),
                "procedencia": _procedencia("modelo", "Nodos y aristas dados por el modelo"),
            }
            sustituida = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    grado = {n: 0 for n in ids}
    for arista in a.aristas:
        grado[arista.desde] += 1
        if not a.dirigido:
            grado[arista.hasta] += 1
    return {
        "id": elemento_id,
        "sustituida": sustituida,
        "nodos": len(ids),
        "aristas": len(a.aristas),
        "grado": grado,
        "siguiente": f"Ejecuta un algoritmo con estudio_recorrido(grafo='{elemento_id}', …)",
    }


class RecorridoArgs(_Args):
    grafo: str
    algoritmo: Literal["dijkstra", "bfs", "dfs"]
    origen: str
    destino: str | None = None


async def _recorrido(user: dict, a: RecorridoArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            grafo = esc.elemento(escena, a.grafo)
            if grafo is None or grafo["tipo"] != "grafo":
                raise esc.EscenaError(f"«{a.grafo}» no es un grafo de la escena")
            ejecucion = algoritmos.recorrer(
                a.algoritmo,
                [n["id"] for n in grafo["nodos"]],
                grafo["aristas"],
                grafo["dirigido"],
                a.origen,
                a.destino,
                {nodo["id"]: nodo["etiqueta"] for nodo in grafo["nodos"]},
            )
            grafo["recorrido"] = {
                "algoritmo": a.algoritmo,
                "origen": a.origen,
                "destino": a.destino,
                **ejecucion,
            }
            # El recorrido lo calcula el engine, pero los nodos y las aristas
            # siguen siendo lo que dijo el modelo: si representan anatomía o un
            # mapa, nadie lo ha verificado. La etiqueta no puede decir
            # «Calculado» de algo cuya materia prima es texto del modelo.
            grafo["procedencia"] = _procedencia(
                "modelo",
                f"Nodos y aristas dados por el modelo; {a.algoritmo.upper()} "
                "ejecutado por el engine",
            )
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {
        "grafo": a.grafo,
        "algoritmo": a.algoritmo,
        "fotogramas": len(ejecucion["fotogramas"]),
        "resultado": ejecucion["resultado"],
        "nota": "El alumno lo reproduce paso a paso con el reproductor del grafo",
    }


class OrdenacionArgs(_Args):
    algoritmo: Literal["burbuja", "seleccion", "insercion", "quicksort", "mergesort"]
    valores: list[float] | None = Field(default=None, min_length=2, max_length=algoritmos.MAX_VALORES)
    cantidad: int = Field(default=12, ge=2, le=algoritmos.MAX_VALORES)
    semilla: int = 7
    id: str | None = None
    etiqueta: str | None = Field(default=None, max_length=80)


async def _ordenacion(user: dict, a: OrdenacionArgs) -> dict:
    valores = a.valores or algoritmos.valores_aleatorios(a.cantidad, a.semilla)
    try:
        async with esc.editar(user["id"]) as escena:
            ejecucion = algoritmos.ordenar(a.algoritmo, valores)
            elemento_id = esc.resolver_id(escena, "ordenacion", a.id)
            nuevo = {
                "id": elemento_id,
                "tipo": "ordenacion",
                "algoritmo": a.algoritmo,
                "valores": valores,
                **ejecucion,
                "usa": [],
                "etiqueta": a.etiqueta or f"Ordenación: {a.algoritmo}",
                "color": esc.resolver_color(escena, None),
                "procedencia": _procedencia("engine", f"{a.algoritmo} ejecutado por el engine"),
            }
            sustituida = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {
        "id": elemento_id,
        "sustituida": sustituida,
        "valores_iniciales": valores,
        **ejecucion["resultado"],
    }


# --- Química y modelos ----------------------------------------------------------


class MoleculaArgs(_Args):
    nombre: str = Field(
        min_length=1, max_length=80,
        description="Nombre en inglés (caffeine, glucose, ethanol) o CID de PubChem",
    )
    id: str | None = None
    etiqueta: str | None = Field(default=None, max_length=80)


async def _molecula(user: dict, a: MoleculaArgs) -> dict:
    consulta = moleculas.nombre_en_ingles(a.nombre)
    try:
        datos = await moleculas.desde_pubchem(consulta)
    except moleculas.MoleculaNoEncontrada as error:
        datos = moleculas.local(a.nombre)
        if datos is None:
            raise ToolExecutionFailed(str(error)) from error
    except (httpx.HTTPError, ValueError, KeyError) as error:
        datos = moleculas.local(a.nombre)
        if datos is None:
            raise ToolExecutionFailed(
                f"No se pudo consultar PubChem ({type(error).__name__}). Sin red "
                f"solo hay: {', '.join(sorted({v[0] for v in moleculas.LOCALES.values()}))}"
            ) from error
    try:
        async with esc.editar(user["id"]) as escena:
            elemento_id = esc.resolver_id(escena, "molecula", a.id)
            nuevo = {
                "id": elemento_id,
                "tipo": "molecula",
                "nombre": datos["nombre"],
                "atomos": datos["atomos"],
                "enlaces": datos["enlaces"],
                "usa": [],
                "etiqueta": a.etiqueta or datos["nombre"],
                "color": esc.resolver_color(escena, None),
                "procedencia": datos["fuente"],
            }
            sustituida = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {
        "id": elemento_id,
        "sustituida": sustituida,
        "nombre": datos["nombre"],
        "fuente": datos["fuente"]["detalle"],
        **datos["datos"],
    }


def _nombres_de_partes(modelo: dict) -> list[str]:
    """Los nombres que se pueden señalar, sin repetir (varias mallas
    comparten nombre: las tres valvas son «Válvula aórtica»)."""
    return list(dict.fromkeys(modelo["partes"].values()))


class ModeloArgs(_Args):
    modelo: str = Field(
        default="", max_length=64,
        description="Id del catálogo. Vacío = listar los disponibles sin tocar la escena",
    )
    resaltar: list[str] = Field(default_factory=list, max_length=20)
    id: str | None = None
    etiqueta: str | None = Field(default=None, max_length=80)


async def _modelo(user: dict, a: ModeloArgs) -> dict:
    if not a.modelo:
        disponibles = modelos.catalogo()
        return {
            "disponibles": [
                {"id": m["id"], "nombre": m["nombre"], "partes": _nombres_de_partes(m)}
                for m in disponibles
            ],
            "nota": (
                "No hay modelos instalados: no se puede enseñar anatomía ni "
                "piezas reales. No los inventes; dilo y propón otra visualización"
                if not disponibles
                else "Usa el id para cargarlo; las partes se señalan por su nombre"
            ),
        }
    modelo = modelos.buscar(a.modelo)
    if modelo is None:
        raise ToolExecutionFailed(
            f"No hay ningún modelo «{a.modelo}» en el catálogo. Lista los "
            "disponibles con estudio_modelo sin argumentos"
        )
    resaltadas, desconocidas = modelos.normalizar_partes(modelo, a.resaltar)
    try:
        async with esc.editar(user["id"]) as escena:
            elemento_id = esc.resolver_id(escena, "modelo", a.id)
            nuevo = {
                "id": elemento_id,
                "tipo": "modelo",
                "modelo_id": modelo["id"],
                "url": f"/api/estudio/modelos/{modelo['id']}/archivo",
                "partes": modelo["partes"],
                "resaltadas": resaltadas,
                "usa": [],
                "etiqueta": a.etiqueta or modelo["nombre"],
                "color": esc.resolver_color(escena, None),
                "procedencia": _procedencia("catalogo", modelo["fuente"]),
            }
            sustituida = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {
        "id": elemento_id,
        "sustituida": sustituida,
        "partes": _nombres_de_partes(modelo),
        "resaltadas": sorted({modelo["partes"].get(p, p) for p in resaltadas}),
        "no_existen": desconocidas,
    }


# --- Explicación ----------------------------------------------------------------


class PreguntaArg(_Args):
    enunciado: str = Field(min_length=1, max_length=300)
    opciones: list[str] = Field(min_length=2, max_length=5)
    correcta: int = Field(ge=0, description="Índice (desde 0) de la opción correcta")
    explicacion: str = Field(min_length=1, max_length=600)


class PasoArgs(_Args):
    texto: str = Field(min_length=1, max_length=800)
    mostrar: list[str] = Field(default_factory=list, max_length=20)
    ocultar: list[str] = Field(default_factory=list, max_length=20)
    resaltar: list[str] = Field(
        default_factory=list, max_length=20,
        description="Ids de elementos, o «modelo.parte» para una parte de un modelo",
    )
    pregunta: PreguntaArg | None = None
    numero: int | None = Field(
        default=None, ge=1, description="Si existe ese paso (desde 1), lo sustituye"
    )


async def _paso(user: dict, a: PasoArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            ids = esc.ids_de_elementos(escena)
            for clave in ("mostrar", "ocultar", "resaltar"):
                for ref in getattr(a, clave):
                    base, _, parte = ref.partition(".")
                    if base not in ids:
                        raise esc.EscenaError(
                            f"{clave}: «{base}» no es un elemento de la escena "
                            f"(hay: {', '.join(sorted(ids)) or 'ninguno'})"
                        )
                    if parte:
                        elemento = esc.elemento(escena, base)
                        if elemento["tipo"] != "modelo":
                            raise esc.EscenaError(f"«{base}» no tiene partes: no es un modelo")
                        if not modelos.normalizar_partes(
                            {"partes": elemento["partes"]}, [parte]
                        )[0]:
                            raise esc.EscenaError(
                                f"«{base}» no tiene la parte «{parte}». Tiene: "
                                f"{', '.join(_nombres_de_partes(elemento))}"
                            )
            if a.pregunta and a.pregunta.correcta >= len(a.pregunta.opciones):
                raise esc.EscenaError("pregunta.correcta no es el índice de ninguna opción")
            nuevo = {
                "texto": a.texto.strip(),
                "mostrar": a.mostrar,
                "ocultar": a.ocultar,
                "resaltar": a.resaltar,
                "pregunta": a.pregunta.model_dump() if a.pregunta else None,
            }
            pasos = escena["pasos"]
            if a.numero is not None and a.numero <= len(pasos):
                indice = a.numero - 1
                pasos[indice] = nuevo
            else:
                if len(pasos) >= esc.MAX_PASOS:
                    raise esc.EscenaError(f"Como mucho {esc.MAX_PASOS} pasos")
                pasos.append(nuevo)
                indice = len(pasos) - 1
            visibles = sorted(esc.visibles_en(escena, indice))
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {
        "numero": indice + 1,
        "total_pasos": len(escena["pasos"]),
        "se_ve_en_este_paso": visibles,
        "regla": "Un elemento que aparece por primera vez en un «mostrar» está "
        "oculto hasta ese paso. Lo que se ve en los pasos anteriores puede "
        "cambiar al añadir otros: compruébalo al final con estudio_ver_escena",
    }


class IrAPasoArgs(_Args):
    numero: int = Field(ge=1)


async def _ir_a_paso(user: dict, a: IrAPasoArgs) -> dict:
    try:
        escena = await esc.cambiar_paso(user["id"], a.numero - 1)
    except esc.EscenaError as error:
        raise _fallo(error) from error
    paso = escena["pasos"][a.numero - 1]
    return {
        "numero": a.numero,
        "total_pasos": len(escena["pasos"]),
        "texto": paso["texto"],
        "se_ve": sorted(esc.visibles_en(escena, a.numero - 1)),
    }


class QuitarArgs(_Args):
    id: str = Field(min_length=1, max_length=32)


async def _quitar(user: dict, a: QuitarArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            if a.id in esc.ids_de_parametros(escena):
                dependientes = [e["id"] for e in escena["elementos"] if a.id in e.get("usa", [])]
                if dependientes:
                    raise esc.EscenaError(
                        f"El deslizador {a.id} lo usan {', '.join(dependientes)}: "
                        "quítalos o cámbialos antes"
                    )
                escena["parametros"] = [p for p in escena["parametros"] if p["id"] != a.id]
                return_value = {"quitado": a.id, "era": "deslizador"}
            elif esc.elemento(escena, a.id):
                escena["elementos"] = [e for e in escena["elementos"] if e["id"] != a.id]
                limpiados = []
                for numero, paso in enumerate(escena["pasos"], start=1):
                    antes = esc.referencias_de_paso(paso)
                    for clave in ("mostrar", "ocultar", "resaltar"):
                        paso[clave] = [r for r in paso[clave] if r.split(".", 1)[0] != a.id]
                    if len(esc.referencias_de_paso(paso)) != len(antes):
                        limpiados.append(numero)
                return_value = {"quitado": a.id, "era": "elemento", "pasos_que_lo_nombraban": limpiados}
            else:
                raise esc.EscenaError(f"No hay nada con id «{a.id}»")
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return return_value


# --- Inspección -----------------------------------------------------------------


def _resumen_elemento(e: dict) -> dict:
    resumen = {"id": e["id"], "tipo": e["tipo"], "etiqueta": e.get("etiqueta", "")}
    for clave in ("expresion", "modelo", "algoritmo", "nombre", "parametros", "desde", "hasta"):
        if clave in e:
            resumen[clave] = e[clave]
    if e["tipo"] == "grafo":
        resumen["nodos"] = [n["id"] for n in e["nodos"]]
        resumen["aristas"] = len(e["aristas"])
        if e.get("recorrido"):
            resumen["recorrido"] = {
                "algoritmo": e["recorrido"]["algoritmo"],
                "resultado": e["recorrido"]["resultado"],
            }
    if e.get("usa"):
        resumen["deslizadores"] = e["usa"]
    resumen["procedencia"] = e.get("procedencia", {}).get("origen")
    return resumen


async def _ver_escena(user: dict, _: BaseModel) -> dict:
    escena = esc.cargar(user["id"])
    return {
        "titulo": escena["titulo"],
        "modo": escena["modo"],
        "ejes": escena["ejes"],
        "deslizadores": escena["parametros"],
        "elementos": [_resumen_elemento(e) for e in escena["elementos"]],
        "pasos": [
            {
                "numero": i + 1,
                "texto": p["texto"][:140],
                "mostrar": p["mostrar"],
                "ocultar": p["ocultar"],
                "resaltar": p["resaltar"],
                "pregunta": bool(p.get("pregunta")),
            }
            for i, p in enumerate(escena["pasos"])
        ],
        "paso_actual": escena["paso_actual"] + 1 if escena["pasos"] else None,
    }


def revisar(escena: dict) -> dict:
    """Lo que está mal (problemas) o probablemente mal (avisos)."""
    problemas: list[str] = []
    avisos: list[str] = []
    elementos = escena["elementos"]
    if not elementos:
        problemas.append("La escena no tiene ningún elemento")
    ids = esc.ids_de_elementos(escena)
    for numero, paso in enumerate(escena["pasos"], start=1):
        for ref in esc.referencias_de_paso(paso):
            if ref not in ids:
                problemas.append(f"El paso {numero} nombra «{ref}», que ya no existe")
    usados = {p for e in elementos for p in e.get("usa", [])}
    for parametro in escena["parametros"]:
        if parametro["id"] not in usados:
            avisos.append(
                f"El deslizador {parametro['id']} no controla nada: úsalo o quítalo"
            )
    if escena["pasos"]:
        nunca = set(ids) - set().union(
            *(esc.visibles_en(escena, i) for i in range(len(escena["pasos"])))
        )
        for elemento_id in sorted(nunca):
            avisos.append(f"«{elemento_id}» no se ve en ningún paso")
    valores = esc.valores_parametros(escena)
    for e in elementos:
        if e["tipo"] != "funcion":
            continue
        expresion = compilar(e["expresion"], {e["variable"]} | set(valores))
        inicio, fin = e.get("dominio") or escena["ejes"]["x"]
        _, ys = _muestrear(expresion, e["variable"], inicio, fin, valores, 200)
        eje = "z" if escena["modo"] == "3d" else "y"
        for aviso in _avisos_de_rango(ys, escena["ejes"][eje], eje):
            avisos.append(f"{e['id']}: {aviso}")
    if len(elementos) > 1 and not escena["pasos"]:
        avisos.append(
            "Hay varios elementos y ningún paso: una explicación por pasos "
            "(estudio_paso) se entiende mejor que todo a la vez"
        )
    return {"ok": not problemas, "problemas": problemas, "avisos": avisos}


async def _validar(user: dict, _: BaseModel) -> dict:
    return revisar(esc.cargar(user["id"]))


async def _captura(user: dict, _: BaseModel) -> dict:
    captura_id = capturas.reservar(user["id"])
    await events.manager.send(
        user["id"], {"tipo": "estudio_captura", "captura_id": captura_id}
    )
    try:
        imagen = await capturas.recoger(captura_id)
    except TimeoutError as error:
        raise ToolError(str(error)) from error
    return {
        "nota": "Es el lienzo 3D: las etiquetas de texto y los controles no salen en la foto",
        "image": {"media_type": "image/jpeg", "data": base64.b64encode(imagen).decode("ascii")},
    }


# --- Registro -------------------------------------------------------------------

INTRO = (
    "Estudio es la sección de Vibi donde se explican conceptos con "
    "visualizaciones interactivas 2D/3D. "
)

PRIMITIVAS: dict[str, Primitive] = {
    "estudio.nueva_escena": Primitive(
        "estudio.nueva_escena", "Estudio: nueva escena",
        INTRO
        + "Crea (o vacía) la escena. Úsala cuando te pidan explicar, enseñar o "
        "visualizar algo que gane con verse: matemáticas, física, algoritmos, "
        "química o anatomía. Flujo: 1) estudio_nueva_escena; 2) "
        "estudio_parametro para lo que el alumno pueda variar; 3) elementos "
        "(estudio_funcion, estudio_sucesion, estudio_superficie, estudio_marca, "
        "estudio_simulacion, estudio_grafo + estudio_recorrido, "
        "estudio_ordenacion, estudio_molecula, estudio_modelo); 4) la "
        "explicación por pasos con estudio_paso, con preguntas de predicción "
        "cuando encajen; 5) estudio_validar y, si dudas, estudio_captura. Nunca "
        "escribas código gráfico. Los números que cuentes, sácalos de lo que "
        "devuelven las herramientas: están calculados por el engine. modo '3d' "
        "solo si hace falta profundidad (superficies, moléculas, modelos).",
        PERMISOS, EFECTOS, NuevaEscenaArgs, _nueva_escena,
    ),
    "estudio.ejes": Primitive(
        "estudio.ejes", "Estudio: ajustar ejes",
        "Cambia los rangos de los ejes de la escena de Estudio (o los oculta). "
        "Úsala cuando una herramienta avise de que algo se sale de los ejes.",
        PERMISOS, EFECTOS, EjesArgs, _ejes,
    ),
    "estudio.parametro": Primitive(
        "estudio.parametro", "Estudio: deslizador",
        "Crea o cambia un deslizador que el alumno mueve en Estudio. Su id se "
        "usa como variable en las expresiones (sin(a*x)), como «hasta» de una "
        "sucesión o como parámetro de una simulación. Todo lo que dependa de "
        "él se recalcula en vivo.",
        PERMISOS, EFECTOS, ParametroArgs, _parametro,
    ),
    "estudio.funcion": Primitive(
        "estudio.funcion", "Estudio: función",
        "Dibuja y = f(x) en Estudio. Sintaxis: + - * / ^, sin, cos, tan, exp, "
        "log/ln, sqrt, abs, floor, mod(a,b), factorial, pi, e; los productos "
        "con * (2*x). Con el mismo id sustituye a la anterior. Devuelve "
        "valores calculados y avisa si la curva se sale de los ejes.",
        PERMISOS, EFECTOS, FuncionArgs, _funcion,
    ),
    "estudio.sucesion": Primitive(
        "estudio.sucesion", "Estudio: sucesión o serie",
        "Dibuja los términos a_n (o, con acumulada=true, las sumas parciales) "
        "de una sucesión en Estudio: barras, puntos o línea. «hasta» puede ser "
        "un deslizador para que el alumno añada términos. Devuelve los "
        "términos y sumas calculados: úsalos al explicar.",
        PERMISOS, EFECTOS, SucesionArgs, _sucesion,
    ),
    "estudio.superficie": Primitive(
        "estudio.superficie", "Estudio: superficie",
        "Dibuja z = f(x, y) sobre los ejes x e y de una escena 3d de Estudio, "
        "coloreada por altura.",
        PERMISOS, EFECTOS, SuperficieArgs, _superficie,
    ),
    "estudio.marca": Primitive(
        "estudio.marca", "Estudio: punto, vector o etiqueta",
        "Pone en la escena de Estudio un punto, un vector (flecha de «desde» a "
        "«posicion») o una etiqueta de texto, en coordenadas de los ejes. Las "
        "coordenadas pueden ser expresiones con deslizadores (['cos(a)', "
        "'sin(a)']) para que se muevan.",
        PERMISOS, EFECTOS, MarcaArgs, _marca,
    ),
    "estudio.simulacion": Primitive(
        "estudio.simulacion", "Estudio: simulación física",
        "Simula un sistema físico en Estudio; la física la integra el engine. "
        "Modelos y parámetros: " + _descripcion_modelos() + ". Cada parámetro "
        "puede ser un número o el id de un deslizador. Devuelve magnitudes "
        "calculadas (periodos, alcance…) para contarlas sin inventar.",
        PERMISOS, EFECTOS, SimulacionArgs, _simulacion,
    ),
    "estudio.grafo": Primitive(
        "estudio.grafo", "Estudio: grafo",
        "Dibuja un grafo en Estudio (hasta 30 nodos), con pesos en las "
        "aristas. Después, estudio_recorrido ejecuta un algoritmo sobre él.",
        PERMISOS, EFECTOS, GrafoArgs, _grafo,
    ),
    "estudio.recorrido": Primitive(
        "estudio.recorrido", "Estudio: ejecutar algoritmo de grafos",
        "Ejecuta Dijkstra, BFS o DFS sobre un grafo de la escena y lo deja "
        "animado paso a paso. Devuelve el orden de visita, las distancias y el "
        "camino calculados por el engine.",
        PERMISOS, EFECTOS, RecorridoArgs, _recorrido,
    ),
    "estudio.ordenacion": Primitive(
        "estudio.ordenacion", "Estudio: algoritmo de ordenación",
        "Ejecuta burbuja, selección, inserción, quicksort o mergesort sobre "
        "unos valores (o aleatorios) y lo deja animado con barras. Devuelve "
        "comparaciones y escrituras reales.",
        PERMISOS, EFECTOS, OrdenacionArgs, _ordenacion,
    ),
    "estudio.molecula": Primitive(
        "estudio.molecula", "Estudio: molécula 3D",
        "Carga una molécula con su geometría 3D real de PubChem (por nombre "
        "en inglés o CID) en Estudio. Devuelve fórmula, masa molar y número de "
        "átomos de la fuente. Mejor en una escena 3d.",
        PERMISOS, EFECTOS, MoleculaArgs, _molecula,
    ),
    "estudio.modelo": Primitive(
        "estudio.modelo", "Estudio: modelo 3D curado",
        "Carga en Estudio un modelo 3D revisado del catálogo local (anatomía, "
        "piezas) y resalta partes. Sin argumentos, lista los que hay. Nunca "
        "inventes un modelo que no esté en el catálogo.",
        PERMISOS, EFECTOS, ModeloArgs, _modelo,
    ),
    "estudio.paso": Primitive(
        "estudio.paso", "Estudio: paso de la explicación",
        "Añade (o sustituye, con numero) un paso de la explicación guiada de "
        "Estudio: el texto que lee el alumno, qué elementos aparecen "
        "(mostrar), desaparecen (ocultar) o se resaltan, y opcionalmente una "
        "pregunta de predicción con su explicación. Un elemento nombrado por "
        "primera vez en «mostrar» queda oculto hasta ese paso.",
        PERMISOS, EFECTOS, PasoArgs, _paso,
    ),
    "estudio.ir_a_paso": Primitive(
        "estudio.ir_a_paso", "Estudio: ir a un paso",
        "Lleva a todas las pantallas del usuario al paso indicado de la "
        "explicación de Estudio. Úsala para ir al ritmo de lo que estás "
        "contando, sobre todo por voz.",
        PERMISOS, EFECTOS, IrAPasoArgs, _ir_a_paso,
    ),
    "estudio.quitar": Primitive(
        "estudio.quitar", "Estudio: quitar",
        "Quita un elemento o un deslizador de la escena de Estudio.",
        PERMISOS, EFECTOS, QuitarArgs, _quitar,
    ),
    "estudio.ver_escena": Primitive(
        "estudio.ver_escena", "Estudio: ver la escena",
        "Resume la escena actual de Estudio: elementos, deslizadores y pasos. "
        "Úsala antes de modificar una escena que no has creado en este turno.",
        SOLO_LECTURA, (), EmptyArguments, _ver_escena,
    ),
    "estudio.validar": Primitive(
        "estudio.validar", "Estudio: revisar la escena",
        "Revisa la escena de Estudio: referencias rotas, deslizadores que no "
        "controlan nada, elementos que nunca se ven, curvas fuera de los ejes. "
        "Llámala al terminar de montar una escena.",
        SOLO_LECTURA, (), EmptyArguments, _validar,
    ),
    "estudio.captura": Primitive(
        "estudio.captura", "Estudio: mirar la escena",
        "Devuelve una imagen de la escena de Estudio tal como la ve el alumno, "
        "para comprobar que se entiende. Necesita la sección Estudio abierta.",
        SOLO_LECTURA, (), EmptyArguments, _captura,
    ),
}

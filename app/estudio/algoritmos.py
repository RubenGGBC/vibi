"""Algoritmos ejecutados de verdad, fotograma a fotograma.

Cada algoritmo devuelve dos cosas: los **fotogramas** que pinta el cliente (qué
nodo se está mirando, qué barras se comparan) y el **resultado**, que es lo que
el modelo cuenta. Las dos salen de la misma ejecución, así que la animación y
la explicación no pueden contradecirse.
"""
from __future__ import annotations

import heapq
import math
import random
from collections import deque

MAX_NODOS = 30
MAX_ARISTAS = 120
MAX_VALORES = 40
MAX_FOTOGRAMAS = 1500

ALGORITMOS_GRAFO = ("dijkstra", "bfs", "dfs")
ALGORITMOS_ORDENACION = ("burbuja", "seleccion", "insercion", "quicksort", "mergesort")


class AlgoritmoInvalido(ValueError):
    pass


# --- Grafos -----------------------------------------------------------------


def disposicion_circular(ids: list[str]) -> dict[str, list[float]]:
    """Posiciones en un círculo de radio proporcional al número de nodos."""
    n = len(ids)
    radio = max(2.0, 0.55 * n)
    return {
        nodo: [
            round(radio * math.cos(math.pi / 2 - 2 * math.pi * i / n), 4),
            round(radio * math.sin(math.pi / 2 - 2 * math.pi * i / n), 4),
            0.0,
        ]
        for i, nodo in enumerate(ids)
    }


def _vecinos(
    nodos: list[str], aristas: list[dict], dirigido: bool
) -> dict[str, list[tuple[str, float]]]:
    adyacencia: dict[str, list[tuple[str, float]]] = {nodo: [] for nodo in nodos}
    for arista in aristas:
        adyacencia[arista["desde"]].append((arista["hasta"], arista["peso"]))
        if not dirigido:
            adyacencia[arista["hasta"]].append((arista["desde"], arista["peso"]))
    # Orden estable: a igualdad, por id. Hace la ejecución reproducible y
    # que lo que el modelo cuente sea lo que se ve.
    for lista in adyacencia.values():
        lista.sort(key=lambda par: par[0])
    return adyacencia


def _camino(previo: dict[str, str | None], destino: str) -> list[str]:
    camino = [destino]
    while previo.get(camino[-1]) is not None:
        camino.append(previo[camino[-1]])  # type: ignore[arg-type]
    return list(reversed(camino))


def recorrer(
    algoritmo: str,
    nodos: list[str],
    aristas: list[dict],
    dirigido: bool,
    origen: str,
    destino: str | None,
) -> dict:
    if algoritmo not in ALGORITMOS_GRAFO:
        raise AlgoritmoInvalido(
            f"Algoritmo desconocido. Disponibles: {', '.join(ALGORITMOS_GRAFO)}"
        )
    for nombre, valor in (("origen", origen), ("destino", destino)):
        if valor is not None and valor not in nodos:
            raise AlgoritmoInvalido(f"El {nombre} «{valor}» no es un nodo del grafo")
    if algoritmo == "dijkstra" and any(a["peso"] < 0 for a in aristas):
        raise AlgoritmoInvalido("Dijkstra no admite pesos negativos")

    adyacencia = _vecinos(nodos, aristas, dirigido)
    fotogramas: list[dict] = []

    def foto(**datos) -> None:
        if len(fotogramas) < MAX_FOTOGRAMAS:
            fotogramas.append(datos)

    if algoritmo == "dijkstra":
        distancia = {nodo: math.inf for nodo in nodos}
        previo: dict[str, str | None] = {nodo: None for nodo in nodos}
        distancia[origen] = 0.0
        visitados: list[str] = []
        cola = [(0.0, origen)]
        foto(
            actual=None, visitados=[], frontera=[origen], arista=None,
            distancias=_distancias(distancia),
            mensaje=f"Empezamos en {origen} con distancia 0; el resto, infinito",
        )
        while cola:
            d, u = heapq.heappop(cola)
            if u in visitados or d > distancia[u]:
                continue
            visitados.append(u)
            frontera = sorted({v for _, v in cola if v not in visitados})
            foto(
                actual=u, visitados=list(visitados), frontera=frontera, arista=None,
                distancias=_distancias(distancia),
                mensaje=f"Saco {u}: es el no visitado más cercano ({_fmt(d)})",
            )
            if destino is not None and u == destino:
                break
            for v, peso in adyacencia[u]:
                if v in visitados:
                    continue
                nueva = d + peso
                if nueva < distancia[v]:
                    antes = distancia[v]
                    distancia[v] = nueva
                    previo[v] = u
                    heapq.heappush(cola, (nueva, v))
                    mensaje = (
                        f"{u}→{v}: {_fmt(d)} + {_fmt(peso)} = {_fmt(nueva)} "
                        f"mejora {_fmt(antes)}"
                    )
                else:
                    mensaje = (
                        f"{u}→{v}: {_fmt(nueva)} no mejora {_fmt(distancia[v])}"
                    )
                foto(
                    actual=u, visitados=list(visitados),
                    frontera=sorted({x for _, x in cola if x not in visitados}),
                    arista=[u, v], distancias=_distancias(distancia), mensaje=mensaje,
                )
        resultado: dict = {
            "orden_de_visita": visitados,
            "distancias": _distancias(distancia),
        }
        if destino is not None:
            if math.isinf(distancia[destino]):
                resultado["camino"] = []
                resultado["mensaje"] = f"No hay camino de {origen} a {destino}"
            else:
                resultado["camino"] = _camino(previo, destino)
                resultado["coste"] = distancia[destino]
        fin = {
            "actual": None, "visitados": visitados, "frontera": [], "arista": None,
            "distancias": _distancias(distancia),
            "camino": resultado.get("camino", []),
            "mensaje": _mensaje_final(resultado, origen, destino),
        }
        foto(**fin)
        return {"fotogramas": fotogramas, "resultado": resultado}

    # BFS y DFS comparten esqueleto; cambia la estructura de la frontera.
    # Cada entrada de la frontera recuerda desde dónde se metió: en DFS un
    # nodo puede entrar varias veces, y su padre en el árbol es el de la
    # entrada que se acaba visitando, no el de la primera.
    previo = {nodo: None for nodo in nodos}
    visitados = []
    descubiertos = {origen}
    entradas: deque[tuple[str, str | None]] = deque([(origen, None)])
    nombre_estructura = "cola" if algoritmo == "bfs" else "pila"

    def frontera() -> list[str]:
        return [nodo for nodo, _ in entradas]

    foto(
        actual=None, visitados=[], frontera=[origen], arista=None,
        mensaje=f"Meto {origen} en la {nombre_estructura}",
    )
    while entradas:
        u, padre = entradas.popleft() if algoritmo == "bfs" else entradas.pop()
        if u in visitados:
            continue
        visitados.append(u)
        previo[u] = padre
        foto(
            actual=u, visitados=list(visitados), frontera=frontera(),
            arista=None, mensaje=f"Visito {u} (sale de la {nombre_estructura})",
        )
        if destino is not None and u == destino:
            break
        # En la pila se meten al revés para que salga antes el menor id.
        vecinos = adyacencia[u] if algoritmo == "bfs" else list(reversed(adyacencia[u]))
        for v, _ in vecinos:
            if algoritmo == "bfs" and v in descubiertos:
                continue
            if algoritmo == "dfs" and v in visitados:
                continue
            descubiertos.add(v)
            entradas.append((v, u))
            foto(
                actual=u, visitados=list(visitados), frontera=frontera(),
                arista=[u, v], mensaje=f"Meto {v} (vecino de {u}) en la {nombre_estructura}",
            )
    resultado = {"orden_de_visita": visitados}
    if destino is not None:
        resultado["camino"] = _camino(previo, destino) if destino in visitados else []
        if algoritmo == "bfs" and resultado["camino"]:
            resultado["aristas_del_camino"] = len(resultado["camino"]) - 1
    foto(
        actual=None, visitados=visitados, frontera=[], arista=None,
        camino=resultado.get("camino", []),
        mensaje=_mensaje_final(resultado, origen, destino),
    )
    return {"fotogramas": fotogramas, "resultado": resultado}


def _fmt(valor: float) -> str:
    if math.isinf(valor):
        return "∞"
    return str(int(valor)) if float(valor).is_integer() else f"{valor:g}"


def _distancias(distancia: dict[str, float]) -> dict[str, float | None]:
    return {
        nodo: (None if math.isinf(valor) else valor)
        for nodo, valor in distancia.items()
    }


def _mensaje_final(resultado: dict, origen: str, destino: str | None) -> str:
    orden = " → ".join(resultado["orden_de_visita"])
    if destino is None:
        return f"Terminado. Orden de visita: {orden}"
    if not resultado.get("camino"):
        return f"No hay camino de {origen} a {destino}"
    texto = f"Camino: {' → '.join(resultado['camino'])}"
    if "coste" in resultado:
        texto += f" (coste {_fmt(resultado['coste'])})"
    return texto


# --- Ordenación -------------------------------------------------------------


def valores_aleatorios(cantidad: int, semilla: int) -> list[int]:
    generador = random.Random(semilla)
    return [generador.randint(1, 99) for _ in range(cantidad)]


def ordenar(algoritmo: str, valores: list[float]) -> dict:
    if algoritmo not in ALGORITMOS_ORDENACION:
        raise AlgoritmoInvalido(
            f"Algoritmo desconocido. Disponibles: {', '.join(ALGORITMOS_ORDENACION)}"
        )
    a = list(valores)
    n = len(a)
    fotogramas: list[dict] = []
    cuenta = {"comparaciones": 0, "escrituras": 0}
    fijados: set[int] = set()

    def foto(mensaje: str, comparando=(), escribiendo=(), pivote=None) -> None:
        if len(fotogramas) < MAX_FOTOGRAMAS:
            fotogramas.append(
                {
                    "valores": list(a),
                    "comparando": list(comparando),
                    "escribiendo": list(escribiendo),
                    "pivote": pivote,
                    "ordenados": sorted(fijados),
                    "mensaje": mensaje,
                }
            )

    def menor(i: int, j: int) -> bool:
        cuenta["comparaciones"] += 1
        return a[i] < a[j]

    def intercambiar(i: int, j: int) -> None:
        a[i], a[j] = a[j], a[i]
        cuenta["escrituras"] += 2

    foto("Estado inicial")
    if algoritmo == "burbuja":
        for fin in range(n - 1, 0, -1):
            hubo = False
            for i in range(fin):
                foto(f"Comparo {_fmt(a[i])} y {_fmt(a[i + 1])}", comparando=(i, i + 1))
                if menor(i + 1, i):
                    intercambiar(i, i + 1)
                    hubo = True
                    foto("Están al revés: los cambio", escribiendo=(i, i + 1))
            fijados.add(fin)
            if not hubo:
                fijados.update(range(fin))
                foto("Una pasada sin cambios: ya está ordenado")
                break
        fijados.update(range(n))
    elif algoritmo == "seleccion":
        for i in range(n):
            minimo = i
            for j in range(i + 1, n):
                foto(
                    f"¿{_fmt(a[j])} es menor que el mínimo {_fmt(a[minimo])}?",
                    comparando=(minimo, j), pivote=minimo,
                )
                if menor(j, minimo):
                    minimo = j
            if minimo != i:
                intercambiar(i, minimo)
                foto(f"Llevo el mínimo ({_fmt(a[i])}) a la posición {i}", escribiendo=(i, minimo))
            fijados.add(i)
    elif algoritmo == "insercion":
        fijados.add(0)
        for i in range(1, n):
            j = i
            while j > 0:
                foto(f"Comparo {_fmt(a[j])} con {_fmt(a[j - 1])}", comparando=(j - 1, j))
                if not menor(j, j - 1):
                    break
                intercambiar(j, j - 1)
                foto(f"{_fmt(a[j - 1])} avanza una posición", escribiendo=(j - 1, j))
                j -= 1
            fijados.update(range(i + 1))
    elif algoritmo == "quicksort":
        def particion(lo: int, hi: int) -> int:
            foto(f"Pivote: {_fmt(a[hi])}", pivote=hi)
            i = lo
            for j in range(lo, hi):
                foto(f"¿{_fmt(a[j])} < pivote {_fmt(a[hi])}?", comparando=(j, hi), pivote=hi)
                if menor(j, hi):
                    if i != j:
                        intercambiar(i, j)
                        foto("Va a la izquierda del pivote", escribiendo=(i, j), pivote=hi)
                    i += 1
            if i != hi:
                intercambiar(i, hi)
            fijados.add(i)
            foto(f"El pivote queda en su sitio definitivo ({i})", escribiendo=(i, hi))
            return i

        pila = [(0, n - 1)]
        while pila:
            lo, hi = pila.pop()
            if lo > hi:
                continue
            if lo == hi:
                fijados.add(lo)
                continue
            p = particion(lo, hi)
            pila.append((p + 1, hi))
            pila.append((lo, p - 1))
    else:  # mergesort, de abajo arriba para no depender de la recursión
        ancho = 1
        while ancho < n:
            for lo in range(0, n, 2 * ancho):
                medio = min(lo + ancho, n)
                hi = min(lo + 2 * ancho, n)
                izquierda, derecha = a[lo:medio], a[medio:hi]
                if not derecha:
                    continue
                i = j = 0
                k = lo
                while i < len(izquierda) and j < len(derecha):
                    cuenta["comparaciones"] += 1
                    foto(
                        f"Mezclo: {_fmt(izquierda[i])} contra {_fmt(derecha[j])}",
                        comparando=(lo + i, medio + j),
                    )
                    if derecha[j] < izquierda[i]:
                        a[k] = derecha[j]
                        j += 1
                    else:
                        a[k] = izquierda[i]
                        i += 1
                    cuenta["escrituras"] += 1
                    k += 1
                for resto in izquierda[i:] + derecha[j:]:
                    a[k] = resto
                    cuenta["escrituras"] += 1
                    k += 1
                foto(f"Tramo {lo}–{hi - 1} mezclado", escribiendo=tuple(range(lo, hi)))
            ancho *= 2
        fijados.update(range(n))

    fijados.update(range(n))
    foto("Ordenado")
    return {
        "fotogramas": fotogramas,
        "resultado": {
            "ordenado": a,
            "comparaciones": cuenta["comparaciones"],
            "escrituras": cuenta["escrituras"],
            "fotogramas": len(fotogramas),
            "recortado": len(fotogramas) >= MAX_FOTOGRAMAS,
        },
    }

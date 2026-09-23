"""Cuánto tarda cada modelo Gemini de `agy` en responder con effort bajo.

Uso: python -m scripts.medir_agy_low [--repeticiones 3] [--prompt "..."]

Mide dos tiempos distintos porque responden a preguntas distintas:

- `total`: lo que pasa desde que se lanza el proceso hasta que imprime. Es lo
  que esperaría alguien que llame a `agy -p` en frío, y lleva dentro el
  arranque de la CLI (unos cuatro segundos en esta máquina).
- `modelo`: el `duration_seconds` que la propia CLI declara en su JSON, o sea
  el turno sin el arranque. Es lo comparable entre modelos.

La diferencia entre ambos no es del modelo, es del proceso, así que se enseña
aparte en vez de dejarla contaminar la comparación.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time

# La lista de modelos y el criterio de cuándo sobra `--effort` ya los sabe el
# ejecutor: se reutilizan en vez de repetirlos aquí a mano.
from app.executors.agy_modelos import ErrorModelos, Modelo, listar

PROMPT_POR_DEFECTO = "Responde solo con la palabra: ok"
# Un turno de charla ronda los cinco segundos; con un minuto sobra para que un
# modelo lento termine y no se queden colgadas las mediciones si uno se atasca.
TIMEOUT_TURNO = 120.0


def modelos_gemini_low(binario: str) -> list[Modelo]:
    """Los Gemini con esfuerzo bajo que `agy` sepa usar hoy.

    Se pregunta en vez de hardcodear porque la lista cambia por su cuenta según
    lo que Google publique: la de hoy tiene 3.8, 3.7, 3.6 flash y 3.1 pro.
    """
    return [
        m
        for m in listar(binario, forzar=True)
        if m.id.startswith("gemini") and "-low" in m.id
    ]


def medir(binario: str, modelo: Modelo, prompt: str) -> tuple[float, float | None, str]:
    """Un turno, cronometrado. Devuelve (total, tiempo declarado, estado)."""
    comando = [binario, "-p", prompt, "--model", modelo.id, "--output-format", "json"]
    # Solo cuando el nombre no trae ya el esfuerzo; si lo trae, la CLI protesta
    # en el arranque y sigue sin la bandera.
    if not modelo.effort_en_el_nombre:
        comando += ["--effort", "low"]

    arranque = time.monotonic()
    try:
        resultado = subprocess.run(
            comando, capture_output=True, text=True, timeout=TIMEOUT_TURNO
        )
    except subprocess.TimeoutExpired:
        return TIMEOUT_TURNO, None, "timeout"
    total = time.monotonic() - arranque

    if resultado.returncode != 0:
        return total, None, f"error ({resultado.returncode})"
    # La CLI puede escribir avisos antes del JSON, así que se busca la última
    # línea que parsee en vez de dar por hecho que la salida entera es el objeto.
    for linea in reversed(resultado.stdout.strip().splitlines()):
        try:
            datos = json.loads(linea)
        except json.JSONDecodeError:
            continue
        return total, datos.get("duration_seconds"), datos.get("status", "?")
    return total, None, "sin json"


def resumen(valores: list[float]) -> str:
    if not valores:
        return "    —"
    return (
        f"{statistics.median(valores):6.2f}  "
        f"(min {min(valores):5.2f}  max {max(valores):5.2f})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeticiones", type=int, default=3, help="Turnos por modelo")
    parser.add_argument("--prompt", default=PROMPT_POR_DEFECTO)
    parser.add_argument("--binario", default="agy", help="Ruta del ejecutable agy")
    parser.add_argument(
        "--modelo",
        action="append",
        default=[],
        help="Mide solo este modelo (repetible); por defecto, todos los gemini low",
    )
    args = parser.parse_args()

    if args.modelo:
        modelos = [Modelo(id=m, etiqueta=m) for m in args.modelo]
    else:
        try:
            modelos = modelos_gemini_low(args.binario)
        except ErrorModelos as error:
            print(error)
            return 1
    if not modelos:
        print("agy no ofrece ningún Gemini con effort low ahora mismo.")
        return 1

    print(f"Prompt: {args.prompt!r}")
    print(f"{len(modelos)} modelos × {args.repeticiones} turnos\n")

    tabla: list[tuple[str, list[float], list[float]]] = []
    for modelo in modelos:
        totales: list[float] = []
        declarados: list[float] = []
        print(f"{modelo.id}", end="", flush=True)
        for _ in range(args.repeticiones):
            total, declarado, estado = medir(args.binario, modelo, args.prompt)
            if estado == "SUCCESS":
                totales.append(total)
                if declarado is not None:
                    declarados.append(declarado)
                print(f"  {total:.2f}s", end="", flush=True)
            else:
                print(f"  [{estado}]", end="", flush=True)
        print()
        tabla.append((modelo.id, totales, declarados))

    print(f"\n{'modelo':<26}{'modelo (mediana)':<32}{'total con arranque'}")
    print("-" * 84)
    # De más rápido a más lento por el tiempo del modelo, que es la pregunta;
    # los que no dieron ninguna medida buena caen al final.
    def orden(fila):
        _, _, declarados = fila
        return statistics.median(declarados) if declarados else float("inf")

    for id_, totales, declarados in sorted(tabla, key=orden):
        print(f"{id_:<26}{resumen(declarados):<32}{resumen(totales)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

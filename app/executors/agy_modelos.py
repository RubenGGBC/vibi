"""Qué modelos sabe usar agy, y cómo entender `/model` cuando llega por el hilo.

`agy models` es un subcomando real de la CLI: le pregunta a Google y tarda
sobre dos segundos, medido en esta máquina. Por eso la lista no vive
hardcodeada —cambia por su cuenta según lo que Google publique— y se cachea en
vez de consultarse en cada turno.
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from typing import Literal

from .agy_process import SUFIJOS_DE_ESFUERZO

EFFORTS_VALIDOS = ("low", "medium", "high")

# `agy models` tarda ~2 s (pregunta a Google) y la lista no cambia turno a
# turno: cachearla evita pagar esos dos segundos en cada `/model` y en cada
# apertura del selector.
TTL_CACHE = 300.0


class ErrorModelos(Exception):
    pass

# El prefijo tiene que cerrar en palabra: «/modelfoo» no es «/model foo». No
# se exige nada después porque `/model` a secas es un comando válido —pide la
# lista— y su forma la decide `interpretar`, no esta regex.
_PREFIJO = re.compile(r"^/model(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class Modelo:
    id: str
    etiqueta: str

    @property
    def effort_en_el_nombre(self) -> bool:
        """Si `--effort` sobra: la CLI lo rechaza para estos, ver `agy_process`."""
        return self.id.endswith(SUFIJOS_DE_ESFUERZO)


_cache: list[Modelo] | None = None
_cache_en: float = 0.0


def listar(binario: str = "", *, forzar: bool = False) -> list[Modelo]:
    """Los modelos que `agy` sabe usar ahora mismo, cacheados unos minutos."""
    global _cache, _cache_en
    if not forzar and _cache is not None and time.monotonic() - _cache_en < TTL_CACHE:
        return _cache
    try:
        resultado = subprocess.run(
            [binario or "agy", "models"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ErrorModelos(
            f"No pude preguntarle a agy qué modelos tiene: {error}"
        ) from error
    _cache = _parsear(resultado.stdout)
    _cache_en = time.monotonic()
    return _cache


def _parsear(salida: str) -> list[Modelo]:
    """De `id<TAB>etiqueta` por línea a una lista de `Modelo`.

    La primera línea —«Fetching available models...»— no lleva tabulador y se
    descarta sola: no es una fila, es el aviso de que la CLI está preguntando.
    """
    modelos = []
    for linea in salida.splitlines():
        id_, tab, etiqueta = linea.partition("\t")
        if not tab:
            continue
        id_ = id_.strip()
        if id_:
            modelos.append(Modelo(id=id_, etiqueta=etiqueta.strip() or id_))
    return modelos


@dataclass(frozen=True)
class Peticion:
    """Lo que pide el comando, ya decidido: no queda nada por interpretar."""

    tipo: Literal["listar", "fijar", "por_defecto", "error"]
    modelo: Modelo | None = None
    effort: str | None = None
    error: str = ""


def es_comando(texto: str) -> bool:
    """Si este mensaje hay que interceptarlo antes de que llegue a Claude o a
    agy, en vez de tratarlo como una frase más de la conversación."""
    return bool(_PREFIJO.match(texto.strip()))


def interpretar(texto: str, modelos: list[Modelo]) -> Peticion:
    """El texto de `/model`, resuelto contra la lista de modelos que hay hoy.

    Recibe la lista en vez de pedirla ella misma porque listarla es una
    llamada a la CLI (~2 s): quien orquesta el comando la pide una vez y la
    pasa, y así esto queda puro y se prueba sin `agy` instalado.
    """
    resto = texto.strip()[len("/model"):].strip()
    if not resto:
        return Peticion("listar")
    if resto.lower() == "default":
        return Peticion("por_defecto")

    partes = resto.split(maxsplit=1)
    id_pedido = partes[0]
    encontrado = next((m for m in modelos if m.id == id_pedido), None)
    if encontrado is None:
        return Peticion(
            "error",
            error=f"No conozco el modelo «{id_pedido}». Escribe /model para ver la lista.",
        )

    if len(partes) == 1:
        return Peticion("fijar", modelo=encontrado)

    if encontrado.effort_en_el_nombre:
        return Peticion(
            "error",
            error=(
                f"«{encontrado.id}» ya lleva el effort en el nombre; "
                "no hace falta indicarlo aparte."
            ),
        )
    effort = partes[1].strip().lower()
    if effort not in EFFORTS_VALIDOS:
        return Peticion(
            "error",
            error=f"El effort tiene que ser low, medium o high (no «{effort}»).",
        )
    return Peticion("fijar", modelo=encontrado, effort=effort)

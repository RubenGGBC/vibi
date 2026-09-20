"""Quién elige cuando el árbol deja varios candidatos y hay que seguir.

`ui.py` para el lote en cuanto una búsqueda da más de un resultado, y hace
bien: tres «Aceptar» son una pregunta, no una opción por defecto. Pero
preguntarle al modelo de chat cuesta un turno entero —medido en este equipo,
entre 4 y 8 segundos— para elegir entre seis cosas que ya están identificadas.

Esto es la otra respuesta: un modelo de decisión, que no genera texto y solo
escoge entre las opciones que le das. Medido el 2026-09-20 contra Jev: 0,5 s y
0,0003 $ por elección.

**Nunca dice «no lo sé».** Le preguntes lo que le preguntes, contesta una de
las opciones, así que el único freno es la confianza que devuelve con ella.
Por debajo del umbral aquí no se elige nada y el lote para como paraba antes:
en el peor caso te comportas como siempre, habiendo perdido medio segundo.
"""
from __future__ import annotations

import json
import os
import urllib.request

# A partir de qué confianza se acepta lo que diga. Va alto a propósito: lo que
# está al otro lado es una GUI de verdad, y el clic que no era no se deshace.
UMBRAL = 0.80

# El modelo de decisión y por dónde se le llama. Vía Opper y no directamente
# contra TypeSafe porque su API propia está en lista de espera y ésta no.
MODELO = "typesafe/jev-1.13.0"
URL = "https://api.opper.ai/v3/compat/v1/systemone"

# Lo que se espera a que conteste. Va muy por debajo del `PRESUPUESTO` de un
# lote: esto está para ahorrar tiempo, no para gastarlo. Si tarda más que
# esto, se decide como se decidía antes.
ESPERA = 3.0


def _clave() -> str:
    return os.environ.get("OPPER_API_KEY", "").strip()


def disponible() -> bool:
    return bool(_clave())


def desempatar(
    estado: str,
    pregunta: str,
    opciones: dict[str, str],
    umbral: float = UMBRAL,
) -> str | None:
    """La opción elegida, o `None` si no hay elección que valga la pena.

    `None` no es un error: es «decide tú». Sale por ahí cuando no hay clave,
    cuando no hay red, cuando la respuesta no se entiende, cuando elige algo
    que no estaba en la lista y cuando no va bastante seguro. Todos esos
    caminos acaban en el mismo sitio, que es el comportamiento de siempre.
    """
    if len(opciones) < 2:
        return None
    clave = _clave()
    if not clave:
        return None

    peticion = urllib.request.Request(
        URL,
        data=json.dumps({
            "model": MODELO,
            "state": estado,
            "questions": {
                "cual": {
                    "type": "choice",
                    "instructions": pregunta,
                    "criteria": dict(opciones),
                },
            },
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {clave}",
        },
    )

    try:
        with urllib.request.urlopen(peticion, timeout=ESPERA) as respuesta:
            contestado = json.loads(respuesta.read())
        elegido = contestado["answers"]["cual"]["choice"]
        confianza = float(contestado["answers"]["cual"]["confidence"])
    except (OSError, ValueError, KeyError, TypeError):
        return None

    if elegido not in opciones:
        return None
    if confianza < umbral:
        return None
    return elegido

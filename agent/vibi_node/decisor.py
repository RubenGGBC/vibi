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

**Varias preguntas van en una sola petición.** Es la idea que más rinde de
`awlevin/typesafe-computer-use`, de donde sale casi todo lo de aquí: partir la
decisión en preguntas independientes —qué clase de acción, sobre cuál de los
elementos— cuesta lo mismo que una, porque el estado se manda una vez, y evita
que el ruido de una pregunta contamine a la otra. La confianza mide
concentración, así que **dos opciones que significan lo mismo siempre se leen
como duda**: mantén las listas mutuamente excluyentes o el umbral te frenará
por algo que no era una duda de verdad.

**Hay dos tipos de pregunta.** Una `eleccion` escoge entre opciones con
nombre; un `juicio` —el `Noul` de TypeSafe— devuelve la probabilidad de que
algo sea cierto, sin lista. El segundo está para comprobar, que es lo que se
hace después de actuar y antes de decir que salió bien.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class Eleccion:
    """Lo que contestó a una pregunta de opciones."""

    opcion: str
    confianza: float
    # Lo que le dio a cada opción. Es lo que distingue «ha elegido» de «ha
    # tenido que elegir»: dos opciones a 0,45 y 0,44 son un empate disfrazado
    # de decisión, y se ve aquí y en ningún otro sitio.
    reparto: dict[str, float] = field(default_factory=dict)

    def seguro(self, umbral: float = UMBRAL) -> bool:
        return self.confianza >= umbral


@dataclass(frozen=True)
class Juicio:
    """Lo que contestó a una pregunta de sí o no: la probabilidad del sí."""

    probabilidad: float


@dataclass(frozen=True)
class Respuesta:
    """Todo lo que volvió de una petición, con lo que costó."""

    respuestas: dict[str, Eleccion | Juicio]
    ms: int = 0

    def eleccion(self, nombre: str) -> Eleccion | None:
        valor = self.respuestas.get(nombre)
        return valor if isinstance(valor, Eleccion) else None

    def juicio(self, nombre: str) -> Juicio | None:
        valor = self.respuestas.get(nombre)
        return valor if isinstance(valor, Juicio) else None


# Lo último que se preguntó y lo que se contestó, para poder contarlo después.
# Un desempate que sale mal es invisible desde fuera —se pulsó algo, y punto—,
# y sin esto la única forma de entender por qué era volver a reproducirlo a
# ciegas. Es la versión mínima de la carpeta de ejecución de
# `typesafe-computer-use`, que guarda cada decisión con su reparto entero.
_ultimo: dict | None = None


def ultimo() -> dict | None:
    """El último juicio emitido, tal cual, o `None` si no ha habido ninguno."""
    return _ultimo


def olvidar() -> None:
    global _ultimo
    _ultimo = None


def _clave() -> str:
    return os.environ.get("OPPER_API_KEY", "").strip()


def disponible() -> bool:
    return bool(_clave())


def eleccion(instrucciones: str, opciones: dict[str, str]) -> dict:
    """Una pregunta de opciones, tal como la espera la API."""
    return {
        "type": "choice",
        "instructions": instrucciones,
        "criteria": dict(opciones),
    }


def juicio(instrucciones: str) -> dict:
    """Una pregunta de sí o no, que vuelve como probabilidad."""
    return {"type": "noul", "instructions": instrucciones}


def _leer(cruda: object) -> Eleccion | Juicio | None:
    if not isinstance(cruda, dict):
        return None
    if "choice" in cruda:
        try:
            confianza = float(cruda["confidence"])
        except (KeyError, TypeError, ValueError):
            return None
        reparto = cruda.get("probabilities") or cruda.get("distribution") or {}
        return Eleccion(
            opcion=str(cruda["choice"]),
            confianza=confianza,
            reparto={
                str(k): float(v)
                for k, v in reparto.items()
                if isinstance(v, (int, float))
            } if isinstance(reparto, dict) else {},
        )
    if "noul" in cruda:
        try:
            return Juicio(probabilidad=float(cruda["noul"]))
        except (TypeError, ValueError):
            return None
    return None


def preguntar(
    estado: object,
    preguntas: dict[str, dict],
    espera: float = ESPERA,
) -> Respuesta | None:
    """Manda el estado con todas sus preguntas de una vez.

    `None` no es un error: es «decide tú». Sale por ahí cuando no hay clave,
    cuando no hay red, cuando tarda más de la cuenta y cuando la respuesta no
    se entiende. Todos esos caminos acaban en el mismo sitio, que es el
    comportamiento de siempre.

    El estado va tal cual si es texto y como JSON si es cualquier otra cosa:
    un árbol dibujado se lee mejor como el dibujo que es, y un puñado de datos
    sueltos —qué pidió, qué hay abierto, qué se hizo antes— se lee mejor con
    sus nombres puestos.
    """
    if not preguntas:
        return None
    clave = _clave()
    if not clave:
        return None

    cuerpo = {
        "model": MODELO,
        "state": estado if isinstance(estado, str) else json.dumps(
            estado, ensure_ascii=False, default=str
        ),
        "questions": preguntas,
    }
    peticion = urllib.request.Request(
        URL,
        data=json.dumps(cuerpo, ensure_ascii=False).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {clave}",
        },
    )

    arrancado = time.monotonic()
    try:
        with urllib.request.urlopen(peticion, timeout=espera) as respuesta:
            contestado = json.loads(respuesta.read())
        crudas = contestado["answers"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(crudas, dict):
        return None

    leidas: dict[str, Eleccion | Juicio] = {}
    for nombre in preguntas:
        leida = _leer(crudas.get(nombre))
        if leida is None:
            return None
        leidas[nombre] = leida

    global _ultimo
    ms = round((time.monotonic() - arrancado) * 1000)
    _ultimo = {
        "preguntas": {
            nombre: pregunta.get("instructions", "")
            for nombre, pregunta in preguntas.items()
        },
        "respuestas": {
            nombre: (
                {"opcion": r.opcion, "confianza": r.confianza, "reparto": r.reparto}
                if isinstance(r, Eleccion)
                else {"probabilidad": r.probabilidad}
            )
            for nombre, r in leidas.items()
        },
        "ms": ms,
    }
    return Respuesta(respuestas=leidas, ms=ms)


def desempatar(
    estado: str,
    pregunta: str,
    opciones: dict[str, str],
    umbral: float = UMBRAL,
) -> str | None:
    """La opción elegida, o `None` si no hay elección que valga la pena.

    `None` sale además cuando elige algo que no estaba en la lista y cuando no
    va bastante seguro, que son las dos formas que tiene de equivocarse sin
    fallar.
    """
    if len(opciones) < 2:
        return None

    respuesta = preguntar(estado, {"cual": eleccion(pregunta, opciones)})
    if respuesta is None:
        return None
    elegida = respuesta.eleccion("cual")
    if elegida is None or elegida.opcion not in opciones:
        return None
    if not elegida.seguro(umbral):
        return None
    return elegida.opcion


def comprobar(
    estado: object, pregunta: str, umbral: float = 0.5
) -> bool | None:
    """¿Salió bien? `None` cuando no hay quien lo diga.

    El umbral va bajo a propósito y no como el de elegir: esto no autoriza
    nada, solo confirma algo que ya se hizo. Lo que cuesta caro aquí es el
    falso «sí», que convierte un mensaje sin enviar en un «ya está enviado»;
    un falso «no» solo hace mirar otra vez.
    """
    respuesta = preguntar(estado, {"ok": juicio(pregunta)})
    if respuesta is None:
        return None
    veredicto = respuesta.juicio("ok")
    if veredicto is None:
        return None
    return veredicto.probabilidad >= umbral

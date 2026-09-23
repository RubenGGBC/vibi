"""El modelo de decisión, del lado del servidor.

`agent/vibi_node/decisor.py` hace esto mismo en la máquina del usuario, donde
elige entre los controles de una ventana. Esto es el otro extremo del mismo
cable: aquí las decisiones no son sobre píxeles sino sobre el trabajo de Vibi
—cuál de estas cinco aplicaciones querías abrir, si esta notificación merece
interrumpir— y por eso no se puede reusar aquel módulo tal cual. Aquel es
síncrono, vive en otro proceso y ni siquiera está instalado aquí.

Lo que sí se reusa es la disciplina, que es lo que vale:

  - **Una sola petición para todas las preguntas.** El estado se manda una
    vez. Dos preguntas cuestan lo que una.
  - **La confianza es el único freno**, porque nunca dice «no lo sé»: le
    preguntes lo que le preguntes, contesta una de las opciones.
  - **`None` significa «decide tú»**, y sale por ahí en cuanto algo no cuadra:
    sin clave, sin red, respuesta rara, opción inventada o poca confianza.
    Todos esos caminos acaban en el comportamiento de antes de que esto
    existiera, que es lo que hace que se pueda enchufar sin miedo.

**Por qué compensa aquí.** Lo que se sustituye es un turno de chat entero:
entre cuatro y ocho segundos en este equipo, y entre tres y ocho céntimos si
lleva herramientas. Esto son 0,5 s y 0,0003 $. Cuando acierta, se ahorra el
turno; cuando duda, se ha perdido medio segundo y se hace lo de siempre. La
apuesta está tan desequilibrada a favor que casi no hay que pensarla.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import httpx

from . import db
from .config import settings

log = logging.getLogger("vibi.decisor")

# A partir de qué confianza se acepta lo que diga. El mismo que el del nodo, y
# por la misma razón: lo que hay al otro lado tiene efectos —una aplicación
# que se abre, un aviso que interrumpe— y equivocarse cuesta más que preguntar.
UMBRAL = 0.80

MODELO = "typesafe/jev-1.13.0"
URL = "https://api.opper.ai/v3/compat/v1/systemone"

# Lo que se espera a que conteste. Corto a propósito: esto se mete delante de
# caminos que ya funcionaban, así que su peor caso tiene que ser invisible.
ESPERA = 3.0

# El cliente se guarda entre llamadas: montar uno por decisión tira el pool de
# conexiones y le suma el saludo TLS a cada pregunta, que es más de lo que
# tarda el modelo en contestar.
_cliente: httpx.AsyncClient | None = None


def cliente() -> httpx.AsyncClient:
    global _cliente
    if _cliente is None or _cliente.is_closed:
        _cliente = httpx.AsyncClient(timeout=ESPERA)
    return _cliente


async def cerrar() -> None:
    global _cliente
    if _cliente is not None and not _cliente.is_closed:
        await _cliente.aclose()
    _cliente = None


@dataclass(frozen=True)
class Eleccion:
    opcion: str
    confianza: float
    reparto: dict[str, float] = field(default_factory=dict)

    def seguro(self, umbral: float = UMBRAL) -> bool:
        return self.confianza >= umbral


@dataclass(frozen=True)
class Juicio:
    probabilidad: float


@dataclass(frozen=True)
class Respuesta:
    respuestas: dict[str, Eleccion | Juicio]
    ms: int = 0

    def eleccion(self, nombre: str) -> Eleccion | None:
        valor = self.respuestas.get(nombre)
        return valor if isinstance(valor, Eleccion) else None

    def juicio(self, nombre: str) -> Juicio | None:
        valor = self.respuestas.get(nombre)
        return valor if isinstance(valor, Juicio) else None


def disponible() -> bool:
    return bool((settings.opper_api_key or "").strip())


def eleccion(instrucciones: str, opciones: dict[str, str]) -> dict:
    return {
        "type": "choice",
        "instructions": instrucciones,
        "criteria": dict(opciones),
    }


def juicio(instrucciones: str) -> dict:
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
            reparto=(
                {
                    str(k): float(v)
                    for k, v in reparto.items()
                    if isinstance(v, (int, float))
                }
                if isinstance(reparto, dict)
                else {}
            ),
        )
    if "noul" in cruda:
        try:
            return Juicio(probabilidad=float(cruda["noul"]))
        except (TypeError, ValueError):
            return None
    return None


async def preguntar(
    estado: object,
    preguntas: dict[str, dict],
    espera: float = ESPERA,
) -> Respuesta | None:
    """Manda el estado con todas sus preguntas de una vez, o `None`."""
    if not preguntas or not disponible():
        return None

    cuerpo = {
        "model": MODELO,
        "state": (
            estado
            if isinstance(estado, str)
            else json.dumps(estado, ensure_ascii=False, default=str)
        ),
        "questions": preguntas,
    }

    arrancado = time.monotonic()
    try:
        respuesta = await cliente().post(
            URL,
            json=cuerpo,
            headers={"Authorization": f"Bearer {settings.opper_api_key.strip()}"},
            timeout=espera,
        )
        respuesta.raise_for_status()
        crudas = respuesta.json()["answers"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        # A nivel de aviso y no de error: esto es un atajo, y que un atajo no
        # esté disponible no es una avería. Lo que viene después funciona.
        log.info("El decisor no ha podido contestar (%s)", error)
        return None
    if not isinstance(crudas, dict):
        return None

    leidas: dict[str, Eleccion | Juicio] = {}
    for nombre in preguntas:
        leida = _leer(crudas.get(nombre))
        if leida is None:
            return None
        leidas[nombre] = leida

    return Respuesta(
        respuestas=leidas, ms=round((time.monotonic() - arrancado) * 1000)
    )


async def desempatar(
    estado: object,
    pregunta: str,
    opciones: dict[str, str],
    umbral: float = UMBRAL,
    *,
    user_id: str | None = None,
    asunto: str = "",
) -> str | None:
    """La opción elegida, o `None` si no hay elección que valga la pena.

    `asunto` es para el registro: un desempate que salió mal es invisible
    desde fuera —se abrió algo, y punto—, y sin dejarlo apuntado la única
    forma de entenderlo después sería reproducirlo a ciegas.
    """
    if len(opciones) < 2:
        return None

    respuesta = await preguntar(estado, {"cual": eleccion(pregunta, opciones)})
    if respuesta is None:
        return None
    elegida = respuesta.eleccion("cual")
    if elegida is None:
        return None

    valida = elegida.opcion in opciones
    acepta = valida and elegida.seguro(umbral)
    if asunto:
        db.log_event(
            "decisor",
            user_id,
            asunto=asunto,
            opciones=len(opciones),
            elegida=elegida.opcion if valida else "",
            confianza=round(elegida.confianza, 4),
            aceptada=acepta,
            ms=respuesta.ms,
        )
    return elegida.opcion if acepta else None


async def comprobar(
    estado: object,
    pregunta: str,
    umbral: float = 0.5,
) -> bool | None:
    """¿Es cierto? `None` cuando no hay quien lo diga.

    El umbral va bajo y no como el de elegir porque esto no autoriza nada:
    solo confirma algo que ya pasó.
    """
    respuesta = await preguntar(estado, {"ok": juicio(pregunta)})
    if respuesta is None:
        return None
    veredicto = respuesta.juicio("ok")
    return None if veredicto is None else veredicto.probabilidad >= umbral

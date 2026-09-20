"""Acciones locales inequívocas que no necesitan una decisión del modelo."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from . import decisor, tools

log = logging.getLogger("vibi.fast_actions")

# La palabra con la que el modelo de decisión dice «ninguna de éstas».
#
# Hace falta porque **nunca se abstiene**: le des las opciones que le des,
# contesta una. Sin una salida escrita en la lista, «abre el correo» sobre un
# catálogo donde solo hay Outlook y Thunderbird elige uno de los dos con toda
# la seguridad del mundo, y lo que había que hacer era preguntar. Es el truco
# del `none` de `awlevin/typesafe-computer-use`, que ofrece «nada de lo que
# hay aquí sirve» como una acción más.
NINGUNA = "ninguna"

# Cuánta seguridad se le exige para abrir algo que solo casaba a medias. Por
# encima del umbral normal a propósito: en `ambiguous` todas las candidatas
# casaban exactamente con lo que pediste y una de ellas es la buena, así que
# la duda es solo cuál; en `not_found` puede no haber ninguna buena, y abrir
# la aplicación equivocada por iniciativa propia es peor que preguntar.
UMBRAL_PARCIAL = 0.90

_LAUNCH = re.compile(r"^\s*(?:abre|inicia|lanza|ejecuta)\s+(.+?)\s*$", re.IGNORECASE)
_TRAILING_PLEASE = re.compile(r",?\s+por\s+favor\s*$", re.IGNORECASE)
_LEADING_ARTICLE = re.compile(
    r"^(?:el|la|los|las|un|una|unos|unas)\s+", re.IGNORECASE
)
_COMPOUND = re.compile(
    r"(?:^|[\s,;])(?:y|e|despu[eé]s|luego|cuando|entonces)(?:$|[\s,;])",
    re.IGNORECASE,
)
_UNSAFE = re.compile(r"[\\/;&|<>`$\"']")
_FLAG = re.compile(r"(?:^|\s)--?[\w]")
_FILE = re.compile(
    r"\.(?:exe|com|bat|cmd|ps1|msi|pdf|docx?|xlsx?|pptx?|txt|zip|rar)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class LaunchAction:
    app: str
    # Lo que se escribió entero, no solo el nombre extraído. No lo usa el
    # lanzador, que solo necesita `app`: lo usa el desempate, y ahí la frase
    # original vale más que el recorte. «abre el chrome del trabajo» y «abre
    # el chrome» dejan el mismo `app` y no se resuelven igual.
    texto: str = ""


@dataclass(frozen=True, slots=True)
class FastActionOutcome:
    handled: bool
    status: str
    response: str = ""
    node_dispatch_ms: int = 0
    node_execution_ms: int = 0


def recognize_launch(
    text: str, attached_tool_ids: tuple[str, ...] = ()
) -> LaunchAction | None:
    """Reconoce solo un imperativo completo y deliberadamente estrecho."""
    if attached_tool_ids:
        return None
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"[.!?]+\s*$", "", cleaned).strip()
    cleaned = _TRAILING_PLEASE.sub("", cleaned).strip()
    match = _LAUNCH.fullmatch(cleaned)
    if match is None:
        return None
    app = _LEADING_ARTICLE.sub("", match.group(1).strip()).strip()
    if not app or len(app) > 200:
        return None
    if app.casefold().startswith("no ") or _COMPOUND.search(app):
        return None
    if "://" in app or _UNSAFE.search(app) or _FLAG.search(app) or _FILE.search(app):
        return None
    return LaunchAction(app=app, texto=str(text or "").strip())


def _milliseconds(value: object) -> int:
    try:
        return max(0, round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _candidate_sentence(candidates: object) -> str:
    if not isinstance(candidates, list):
        return "He encontrado varias aplicaciones. ¿Cuál quieres?"
    labels = [
        str(candidate.get("label") or "").strip()
        for candidate in candidates[:5]
        if isinstance(candidate, dict) and str(candidate.get("label") or "").strip()
    ]
    if not labels:
        return "He encontrado varias aplicaciones. ¿Cuál quieres?"
    if len(labels) == 1:
        joined = labels[0]
    else:
        joined = ", ".join(labels[:-1]) + " y " + labels[-1]
    return f"He encontrado {joined}. ¿Cuál quieres?"


def _opciones_de(candidates: object) -> dict[str, str]:
    """Las candidatas como las lee el modelo de decisión: su id y su nombre."""
    if not isinstance(candidates, list):
        return {}
    opciones: dict[str, str] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        identificador = str(candidate.get("id") or "").strip()
        etiqueta = str(candidate.get("label") or "").strip()
        if identificador and etiqueta:
            opciones[identificador] = etiqueta
    return opciones


async def _elegir_aplicacion(
    user: dict,
    action: LaunchAction,
    candidates: object,
    *,
    parcial: bool,
) -> str | None:
    """Cuál de las candidatas quería, o `None` si no está claro.

    Esto es el desempate de `ui.py` aplicado al catálogo de aplicaciones, y
    está por la misma razón: que haya dos cosas con el mismo nombre no obliga
    a que la persona las separe. Ella escribió «abre discord» y en esta
    máquina hay tres entradas que se llaman así; preguntarle cuál es pedirle
    que resuelva un problema del catálogo.

    Lo que cambia según de dónde venga la lista es si se ofrece una salida.
    En `ambiguous` todas casaban exactamente y la respuesta correcta está
    seguro en la lista. En `not_found` casaban a medias y puede que no esté,
    así que se añade «ninguna»: sin esa opción escrita, el modelo elegiría una
    igualmente, porque abstenerse no es algo que sepa hacer.
    """
    opciones = _opciones_de(candidates)
    if len(opciones) < 2 or not decisor.disponible():
        return None

    if parcial:
        opciones = {
            **opciones,
            NINGUNA: (
                "Ninguna de estas aplicaciones es la que ha pedido, o no hay "
                "forma de saber cuál de ellas quería."
            ),
        }

    elegida = await decisor.desempatar(
        {
            "lo_que_pidio": action.texto or f"abre {action.app}",
            "aplicacion_que_nombro": action.app,
            "coincidencia": "parcial" if parcial else "exacta",
        },
        "De las aplicaciones instaladas en este ordenador, ¿cuál es la que "
        "ha pedido que se abra?",
        opciones,
        UMBRAL_PARCIAL if parcial else decisor.UMBRAL,
        user_id=user.get("id"),
        asunto="abrir_aplicacion",
    )
    if elegida is None or elegida == NINGUNA:
        return None
    return elegida


async def _lanzar(user: dict, app: str) -> dict | None:
    """Manda abrir y devuelve el resultado público del nodo, o `None`."""
    try:
        execution = await tools.execute("devices.launch_app", user, {"app": app})
    except tools.ToolError:
        return None
    public_result = execution.get("result") if isinstance(execution, dict) else None
    return public_result if isinstance(public_result, dict) else None


def _interpretar(
    public_result: dict | None, action: LaunchAction
) -> FastActionOutcome:
    """Traduce lo que contestó el nodo a un desenlace del turno."""
    if not isinstance(public_result, dict):
        return FastActionOutcome(False, "fallback")
    dispatch_ms = _milliseconds(public_result.get("node_dispatch_ms"))
    if public_result.get("state") == "timeout":
        return FastActionOutcome(
            True,
            "timeout",
            "He enviado la orden, pero no he podido confirmar si se abrió.",
            dispatch_ms,
        )

    result = public_result.get("result")
    if not isinstance(result, dict):
        return FastActionOutcome(False, "fallback", node_dispatch_ms=dispatch_ms)
    status = str(result.get("status") or "fallback")
    execution_ms = _milliseconds(result.get("node_execution_ms"))
    if status in {"not_found", "catalog_starting"}:
        return FastActionOutcome(
            False,
            status,
            node_dispatch_ms=dispatch_ms,
            node_execution_ms=execution_ms,
        )
    if status == "ambiguous":
        return FastActionOutcome(
            True,
            status,
            _candidate_sentence(result.get("candidates")),
            dispatch_ms,
            execution_ms,
        )

    app = result.get("app")
    label = (
        str(app.get("label") or "").strip()
        if isinstance(app, dict)
        else ""
    ) or action.app
    if status == "launched":
        return FastActionOutcome(
            True,
            status,
            f"Abriendo {label}.",
            dispatch_ms,
            execution_ms,
        )
    if status == "launch_failed":
        return FastActionOutcome(
            True,
            status,
            f"Encontré {label}, pero Windows no pudo abrirlo.",
            dispatch_ms,
            execution_ms,
        )
    return FastActionOutcome(
        False,
        "fallback",
        node_dispatch_ms=dispatch_ms,
        node_execution_ms=execution_ms,
    )


def _candidatas_de(public_result: dict | None) -> tuple[str, object]:
    """El estado del catálogo y sus candidatas, si las hay."""
    if not isinstance(public_result, dict):
        return "", None
    result = public_result.get("result")
    if not isinstance(result, dict):
        return "", None
    return str(result.get("status") or ""), result.get("candidates")


async def execute_fast_action(user: dict, action: LaunchAction) -> FastActionOutcome:
    """Ejecuta la primitiva normal y solo redacta estados terminales seguros.

    Cuando el catálogo no sabe cuál era, se le pregunta al modelo de decisión
    antes de rendirse. Los dos desenlaces que se intentan salvar cuestan caro
    de formas distintas: `ambiguous` le devuelve la pregunta a quien solo
    quería abrir algo, y `not_found` manda el turno entero al motor de chat,
    que son varios segundos para acabar abriendo lo mismo. Si el desempate no
    lo tiene claro, los dos siguen exactamente como estaban.
    """
    primero = await _lanzar(user, action.app)
    status, candidatas = _candidatas_de(primero)
    if status in {"ambiguous", "not_found"}:
        elegida = await _elegir_aplicacion(
            user, action, candidatas, parcial=status == "not_found"
        )
        if elegida is not None:
            segundo = await _lanzar(user, elegida)
            desenlace = _interpretar(segundo, action)
            if desenlace.handled:
                # El despacho del primer intento también se pagó: contarlo
                # solo una vez escondería justo lo que cuesta este camino.
                return FastActionOutcome(
                    desenlace.handled,
                    desenlace.status,
                    desenlace.response,
                    desenlace.node_dispatch_ms
                    + _milliseconds(
                        primero.get("node_dispatch_ms")
                        if isinstance(primero, dict)
                        else 0
                    ),
                    desenlace.node_execution_ms,
                )
            log.info(
                "El desempate eligió %s pero no se pudo abrir (%s)",
                elegida,
                desenlace.status,
            )
    return _interpretar(primero, action)

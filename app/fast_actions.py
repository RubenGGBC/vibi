"""Acciones locales inequívocas que no necesitan una decisión del modelo."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import tools

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
    return LaunchAction(app=app)


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


async def execute_fast_action(user: dict, action: LaunchAction) -> FastActionOutcome:
    """Ejecuta la primitiva normal y solo redacta estados terminales seguros."""
    try:
        execution = await tools.execute(
            "devices.launch_app", user, {"app": action.app}
        )
    except tools.ToolError:
        return FastActionOutcome(False, "fallback")

    public_result = execution.get("result") if isinstance(execution, dict) else None
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

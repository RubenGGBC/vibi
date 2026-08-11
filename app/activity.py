"""Proyección pública y segura del log de actividad interno."""
import json
from pathlib import Path

from . import db


CATEGORY_EVENT_TYPES: dict[str, tuple[str, ...]] = {
    "tareas": (
        "tarea_creada",
        "plan_generado",
        "tarea_aprobada",
        "tarea_rechazada",
        "tarea_completada",
        "tarea_interrumpida",
        "tarea_reintentada",
    ),
    "conversacion": ("mensaje", "conversacion_reiniciada"),
    "archivos": (
        "archivo_subido",
        "archivo_descargado",
        "archivo_eliminado",
    ),
    "proyectos": (
        "proyecto_clonado",
        "proyecto_eliminado",
        "proyecto_seleccionado",
        "seleccion_proyecto",
    ),
    "herramientas": (
        "herramienta_creada",
        "herramienta_actualizada",
        "herramienta_duplicada",
        "herramienta_activada",
        "herramienta_desactivada",
        "tool_invocation_succeeded",
        "tool_invocation_denied",
        "tool_invocation_failed",
        "skill_created",
        "skill_updated",
        "skill_enabled",
        "skill_disabled",
        "skill_duplicated",
        "skill_run",
    ),
    "cuenta": (
        "login_pwa",
        "login_telegram",
        "configuracion_ia_actualizada",
    ),
    "dispositivos": (
        "nodo_registrado",
        "nodo_revocado",
        "nodo_conectado",
        "nodo_desconectado",
        "nodo_orden_emitida",
        "nodo_orden_resultado",
        "nodo_orden_caducada",
    ),
}

EVENT_TITLES = {
    "tarea_creada": "Tarea creada",
    "plan_generado": "Plan preparado",
    "tarea_aprobada": "Plan aprobado",
    "tarea_rechazada": "Tarea rechazada",
    "tarea_completada": "Tarea completada",
    "tarea_interrumpida": "Ejecución interrumpida",
    "tarea_reintentada": "Tarea reintentada",
    "mensaje": "Mensaje procesado",
    "conversacion_reiniciada": "Conversación reiniciada",
    "archivo_subido": "Archivo subido",
    "archivo_descargado": "Archivo descargado",
    "archivo_eliminado": "Archivo eliminado",
    "proyecto_clonado": "Proyecto clonado",
    "proyecto_eliminado": "Proyecto eliminado",
    "proyecto_seleccionado": "Proyecto seleccionado",
    "seleccion_proyecto": "Proyecto seleccionado",
    "herramienta_creada": "Herramienta creada",
    "herramienta_actualizada": "Herramienta actualizada",
    "herramienta_duplicada": "Herramienta duplicada",
    "herramienta_activada": "Herramienta activada",
    "herramienta_desactivada": "Herramienta desactivada",
    "tool_invocation_succeeded": "Herramienta ejecutada",
    "tool_invocation_denied": "Ejecución de tool rechazada",
    "tool_invocation_failed": "Ejecución de tool fallida",
    "skill_created": "Skill creada",
    "skill_updated": "Skill actualizada",
    "skill_enabled": "Skill activada",
    "skill_disabled": "Skill desactivada",
    "skill_duplicated": "Skill duplicada",
    "skill_run": "Skill ejecutada",
    "login_pwa": "Sesión iniciada",
    "login_telegram": "Telegram vinculado",
    "configuracion_ia_actualizada": "Configuración de IA actualizada",
    "nodo_registrado": "Dispositivo vinculado",
    "nodo_revocado": "Dispositivo revocado",
    "nodo_conectado": "Dispositivo conectado",
    "nodo_desconectado": "Dispositivo desconectado",
    "nodo_orden_emitida": "Orden enviada a un dispositivo",
    "nodo_orden_resultado": "Dispositivo respondió",
    "nodo_orden_caducada": "Orden caducada",
}

TASK_STATE_LABELS = {
    "pendiente": "Pendiente",
    "planificando": "Planificando",
    "esperando_aprobacion": "Esperando aprobación",
    "ejecutando": "En ejecución",
    "completada": "Completada",
    "rechazada": "Rechazada",
    "error": "Error",
}

EVENT_CATEGORY = {
    event_type: category
    for category, event_types in CATEGORY_EVENT_TYPES.items()
    for event_type in event_types
}


def _payload(raw_payload: object) -> dict:
    if not isinstance(raw_payload, str):
        return {}
    try:
        value = json.loads(raw_payload)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_text(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = " ".join(value.split()).strip()
    return normalized[:120] or fallback


def _task_context(payload: dict, user_id: str) -> tuple[str, str | None]:
    task_id = payload.get("task_id")
    if not isinstance(task_id, str):
        return "Tarea del historial", None
    task = db.get_task(task_id)
    if not task or task["user_id"] != user_id:
        return "Tarea del historial", None
    workspace = task.get("workspace")
    project = Path(workspace).name if workspace else "Sin proyecto"
    state = TASK_STATE_LABELS.get(task.get("estado"), "Estado registrado")
    return f"{project} · {state}", f"/tareas/{task_id}"


def _skill_context(payload: dict, user_id: str) -> tuple[str, str | None]:
    skill_id = payload.get("skill_id")
    if not isinstance(skill_id, str):
        return "Skill del historial", "/skills"
    skill = db.get_skill(skill_id)
    if not skill or (
        skill["scope"] == "personal" and skill["owner_user_id"] != user_id
    ):
        return "Skill del historial", "/skills"
    name = _safe_text(skill.get("name"), "Skill sin nombre")
    scope = "Laboratorio" if skill["scope"] == "lab" else "Personal"
    return f"{name} · v{skill['version']} · {scope}", "/skills"


def _node_context(payload: dict, user_id: str) -> tuple[str, str | None]:
    # Sin enlace mientras no exista pantalla de dispositivos en la PWA: un
    # enlace a una ruta inexistente es peor que ninguno.
    node_id = payload.get("node_id")
    node = db.get_node(node_id) if isinstance(node_id, str) else None
    if not node or node["user_id"] != user_id:
        return "Dispositivo del historial", None
    name = _safe_text(node.get("nombre"), "Dispositivo sin nombre")
    capability = payload.get("capability")
    if isinstance(capability, str) and capability:
        estado = _safe_text(payload.get("estado"), "")
        detail = f"{name} · {capability}"
        return (f"{detail} · {estado}" if estado else detail), None
    return name, None


def _event_detail(event_type: str, payload: dict, user_id: str) -> tuple[str, str | None]:
    if event_type in CATEGORY_EVENT_TYPES["dispositivos"]:
        return _node_context(payload, user_id)
    if event_type in CATEGORY_EVENT_TYPES["tareas"]:
        return _task_context(payload, user_id)
    if event_type in ("proyecto_clonado", "proyecto_eliminado"):
        return _safe_text(payload.get("proyecto"), "Proyecto del workspace"), None
    if event_type in ("proyecto_seleccionado", "seleccion_proyecto"):
        project = _safe_text(payload.get("proyecto"), "Proyecto del workspace")
        channel = _safe_text(payload.get("canal"), "Vibi").upper()
        return f"{project} · {channel}", None
    if event_type == "mensaje":
        channel = _safe_text(payload.get("canal"), "Vibi").upper()
        route = {
            "rapida": "Conversación",
            "agentica": "Tarea",
            "herramienta": "Herramienta",
        }.get(payload.get("via"), "Mensaje")
        return f"{channel} · {route}", None
    if event_type == "archivo_subido":
        size = payload.get("size_bytes")
        detail = f"{size:,} bytes" if isinstance(size, int) and size >= 0 else "Archivo personal"
        return detail.replace(",", "."), None
    if event_type in CATEGORY_EVENT_TYPES["archivos"]:
        return "Espacio de archivos personal", None
    if event_type.startswith("skill_"):
        return _skill_context(payload, user_id)
    if event_type in CATEGORY_EVENT_TYPES["herramientas"]:
        scope = payload.get("scope")
        return ("Compartida con el lab" if scope == "lab" else "Ejecución personal"), None
    if event_type == "login_pwa":
        return "Consola web", None
    if event_type == "login_telegram":
        return "Canal de Telegram", None
    if event_type == "configuracion_ia_actualizada":
        return "Modelos y proveedores personales", None
    if event_type == "conversacion_reiniciada":
        return "Nuevo contexto activo", None
    return "Evento conservado por Vibi", None


def serialize_event(event: dict, user_id: str) -> dict:
    """Convierte una fila interna sin filtrar campos sensibles al cliente."""
    event_type = str(event.get("tipo") or "evento_desconocido")
    payload = _payload(event.get("payload"))
    detail, link = _event_detail(event_type, payload, user_id)
    return {
        "id": int(event["id"]),
        "tipo": event_type,
        "categoria": EVENT_CATEGORY.get(event_type, "cuenta"),
        "titulo": EVENT_TITLES.get(event_type, "Actividad registrada"),
        "detalle": detail,
        "creado_en": float(event["ts"]),
        "enlace": link,
    }

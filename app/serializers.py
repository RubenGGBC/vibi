"""Representaciones JSON estables de entidades del core."""
from pathlib import Path

from . import db
from .claude_models import DEFAULT_CLAUDE_MODEL


def serializar_tarea(task: dict) -> dict:
    workspace = task.get("workspace")
    return {
        "id": task["id"],
        "user_id": task["user_id"],
        "prompt": task["prompt"],
        "estado": task["estado"],
        "plan": task.get("plan"),
        "resultado": task.get("resultado"),
        "workspace": workspace,
        "modelo": task.get("modelo", DEFAULT_CLAUDE_MODEL),
        "proyecto": Path(workspace).name if workspace else None,
        "creado_en": task["creado_en"],
        "actualizado_en": task["actualizado_en"],
    }


def serializar_mensaje(message: dict) -> dict:
    """Formato canónico compartido por REST y los eventos en vivo.

    `adjuntos` solo viaja si quien construye el mensaje ya lo trae resuelto,
    para no ir a la base una vez por burbuja. `serializar_mensajes` es el
    camino que lo resuelve de una tanda entera.
    """
    return {
        "id": message["id"],
        "conversation_id": message["conversation_id"],
        "role": message["role"],
        "content": message["content"],
        "origen": message["origen"],
        "client_ref": message.get("client_ref"),
        "tokens_aprox": message.get("tokens_aprox"),
        "created_at": message["created_at"],
        "adjuntos": [
            serializar_archivo(file) for file in message.get("adjuntos") or []
        ],
    }


def serializar_mensajes(messages: list[dict]) -> list[dict]:
    """Serializa una página de mensajes resolviendo sus adjuntos de una vez."""
    ids = [int(message["id"]) for message in messages]
    adjuntos = db.attachments_for_messages(ids)
    return [
        serializar_mensaje(
            {**message, "adjuntos": adjuntos.get(int(message["id"]), [])}
        )
        for message in messages
    ]


def serializar_proyecto(project: dict) -> dict:
    return {
        "id": project["id"],
        "nombre": project["nombre"],
        "slug": project["slug"],
        "descripcion": project.get("descripcion") or "",
        "archivos": int(project.get("archivos") or 0),
        "conversaciones": int(project.get("conversaciones") or 0),
        # Un proyecto sin carpeta conserva sus archivos y conversaciones, pero
        # no puede recibir encargos agénticos: la UI necesita distinguirlo.
        "carpeta": bool(project.get("carpeta", True)),
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
    }


def serializar_conversacion(conversation: dict) -> dict:
    return {
        "id": conversation["id"],
        "titulo": conversation.get("titulo"),
        "estado": conversation["estado"],
        "project_id": conversation.get("project_id"),
        "mensajes": int(conversation.get("mensajes") or 0),
        "created_at": conversation["created_at"],
        "updated_at": conversation["updated_at"],
    }


def serializar_archivo(file: dict) -> dict:
    """No expone storage keys ni rutas absolutas del servidor."""
    return {
        "id": file["id"],
        "name": file["name"],
        "source": file["source"],
        "project_id": file.get("project_id"),
        "relative_path": file.get("relative_path"),
        "media_type": file.get("media_type"),
        "size_bytes": file["size_bytes"],
        "modified_at": file["modified_at"],
        "created_at": file["created_at"],
        "download_url": f"/api/archivos/{file['id']}/contenido",
    }

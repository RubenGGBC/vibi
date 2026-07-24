"""Representaciones JSON estables de entidades del core."""
from pathlib import Path

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
    """Formato canónico compartido por REST y los eventos en vivo."""
    return {
        "id": message["id"],
        "conversation_id": message["conversation_id"],
        "role": message["role"],
        "content": message["content"],
        "origen": message["origen"],
        "client_ref": message.get("client_ref"),
        "tokens_aprox": message.get("tokens_aprox"),
        "created_at": message["created_at"],
    }


def serializar_archivo(file: dict) -> dict:
    """No expone storage keys ni rutas absolutas del servidor."""
    return {
        "id": file["id"],
        "name": file["name"],
        "source": file["source"],
        "relative_path": file.get("relative_path"),
        "media_type": file.get("media_type"),
        "size_bytes": file["size_bytes"],
        "modified_at": file["modified_at"],
        "created_at": file["created_at"],
        "download_url": f"/api/archivos/{file['id']}/contenido",
    }

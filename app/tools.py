"""Catálogo de herramientas sobre primitivas internas explícitamente permitidas."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import db, files


class ToolError(Exception):
    pass


class ToolNotFound(ToolError):
    pass


class ToolDisabled(ToolError):
    pass


class InvalidToolArguments(ToolError):
    pass


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchFilesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", max_length=500)
    limit: int = Field(default=20, ge=1, le=100)


class PrepareDownloadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str = Field(min_length=1, max_length=100)


class ReadFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)


Handler = Callable[[dict, BaseModel], Awaitable[dict]]


@dataclass(frozen=True)
class Primitive:
    id: str
    name: str
    description: str
    permissions: tuple[str, ...]
    effects: tuple[str, ...]
    input_model: type[BaseModel]
    handler: Handler


def serialize_file(file: dict) -> dict:
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


async def _health(_: dict, __: BaseModel) -> dict:
    return {"status": "ok", "service": "Morgana"}


async def _search_files(user: dict, arguments: BaseModel) -> dict:
    parsed = SearchFilesArguments.model_validate(arguments.model_dump())
    found = await asyncio.to_thread(
        files.search_files, user["id"], parsed.query, parsed.limit
    )
    return {"files": [serialize_file(file) for file in found]}


async def _read_file(user: dict, arguments: BaseModel) -> dict:
    parsed = ReadFileArguments.model_validate(arguments.model_dump())
    file, content = await asyncio.to_thread(
        files.read_file, user["id"], parsed.query
    )
    return {
        "files": [serialize_file(file)] if file else [],
        "content": content,
    }


async def _prepare_download(user: dict, arguments: BaseModel) -> dict:
    parsed = PrepareDownloadArguments.model_validate(arguments.model_dump())
    file = db.get_file_for_user(parsed.file_id, user["id"])
    if not file:
        raise ToolNotFound("Archivo no encontrado")
    files.path_for_file(file, user["id"])
    return {"file": serialize_file(file)}


PRIMITIVES: dict[str, Primitive] = {
    "system.health": Primitive(
        "system.health", "Estado de Morgana", "Comprueba que Morgana responde.",
        (), (), EmptyArguments, _health,
    ),
    "files.search": Primitive(
        "files.search", "Buscar mis archivos",
        "Busca por nombre, ruta o contenido dentro del espacio del usuario.",
        ("files:read:self",), ("filesystem:read",),
        SearchFilesArguments, _search_files,
    ),
    "files.read": Primitive(
        "files.read", "Leer uno de mis archivos",
        "Localiza un archivo propio y extrae su texto para responder sobre él.",
        ("files:read:self",), ("filesystem:read",),
        ReadFileArguments, _read_file,
    ),
    "files.prepare_download": Primitive(
        "files.prepare_download", "Preparar descarga",
        "Prepara un archivo propio para descargarlo en el dispositivo actual.",
        ("files:read:self",), ("filesystem:read",),
        PrepareDownloadArguments, _prepare_download,
    ),
}


def _system_tool(primitive: Primitive) -> dict:
    return {
        "id": primitive.id,
        "name": primitive.name,
        "description": primitive.description,
        "scope": "system",
        "primitive_id": primitive.id,
        "permissions": list(primitive.permissions),
        "effects": list(primitive.effects),
        "input_schema": primitive.input_model.model_json_schema(),
        "enabled": True,
        "source": "builtin",
        "created_at": None,
    }


def serialize_custom_tool(tool: dict) -> dict:
    primitive = PRIMITIVES.get(tool["primitive_id"])
    return {
        "id": tool["id"],
        "name": tool["name"],
        "description": tool["description"],
        "scope": tool["scope"],
        "primitive_id": tool["primitive_id"],
        "permissions": list(primitive.permissions) if primitive else [],
        "effects": list(primitive.effects) if primitive else [],
        "input_schema": primitive.input_model.model_json_schema() if primitive else {},
        "bound_arguments": json.loads(tool["bound_arguments"]),
        "enabled": bool(tool["enabled"]) and primitive is not None,
        "source": tool["source"],
        "created_at": tool["created_at"],
    }


def list_catalog(user_id: str) -> list[dict]:
    catalog = [_system_tool(primitive) for primitive in PRIMITIVES.values()]
    catalog.extend(serialize_custom_tool(tool) for tool in db.list_tools_for_user(user_id))
    return catalog


def create_custom_tool(
    user: dict,
    name: str,
    description: str,
    primitive_id: str,
    scope: str,
    bound_arguments: dict,
    source: str = "human",
) -> dict:
    primitive = PRIMITIVES.get(primitive_id)
    if not primitive:
        raise ToolNotFound("La capacidad base no existe")
    if scope == "lab" and not bool(user.get("is_admin")):
        raise ToolError("Solo un administrador puede publicar herramientas del lab")
    try:
        primitive.input_model.model_validate(bound_arguments)
    except ValidationError as error:
        raise InvalidToolArguments("Argumentos preconfigurados inválidos") from error
    tool = db.create_tool(
        scope,
        user["id"] if scope == "personal" else None,
        name.strip(),
        description.strip(),
        primitive_id,
        bound_arguments,
        source,
    )
    return serialize_custom_tool(tool)


async def execute(tool_id: str, user: dict, arguments: dict | None = None) -> dict:
    arguments = arguments or {}
    primitive = PRIMITIVES.get(tool_id)
    effective_arguments = arguments
    audit_id = tool_id
    if primitive is None:
        custom = db.get_tool_for_user(tool_id, user["id"])
        if not custom:
            raise ToolNotFound("Herramienta no encontrada")
        if not custom["enabled"]:
            raise ToolDisabled("La herramienta está desactivada")
        primitive = PRIMITIVES.get(custom["primitive_id"])
        if not primitive:
            raise ToolDisabled("La capacidad base ya no está disponible")
        effective_arguments = {
            **json.loads(custom["bound_arguments"]),
            **arguments,
        }
        audit_id = custom["id"]

    started_at = time.time()
    invocation_id = db.start_tool_invocation(audit_id, user["id"])
    try:
        parsed = primitive.input_model.model_validate(effective_arguments)
        result = await primitive.handler(user, parsed)
    except ValidationError as error:
        db.finish_tool_invocation(invocation_id, "denied", started_at, "invalid_arguments")
        raise InvalidToolArguments("Argumentos inválidos") from error
    except Exception:
        db.finish_tool_invocation(invocation_id, "failed", started_at, "execution_failed")
        raise
    db.finish_tool_invocation(invocation_id, "succeeded", started_at)
    db.log_event("tool_invocation_succeeded", user["id"], tool_id=audit_id)
    return {
        "invocation_id": invocation_id,
        "tool_id": audit_id,
        "status": "succeeded",
        "result": result,
    }

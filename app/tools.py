"""Catálogo de herramientas sobre primitivas internas explícitamente permitidas."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from . import activity, db, files, nodes, tasks


class ToolError(Exception):
    pass


class ToolNotFound(ToolError):
    pass


class ToolDisabled(ToolError):
    pass


class InvalidToolArguments(ToolError):
    pass


class ToolPermissionDenied(ToolError):
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


TaskState = Literal[
    "pendiente",
    "planificando",
    "esperando_aprobacion",
    "ejecutando",
    "completada",
    "rechazada",
    "error",
]
ActivityCategory = Literal[
    "tareas", "conversacion", "archivos", "proyectos", "herramientas", "cuenta"
]


class ListTasksArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: TaskState | None = None
    project: str | None = Field(default=None, min_length=1, max_length=120)
    limit: int = Field(default=20, ge=1, le=100)


class RecentActivityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: ActivityCategory | None = None
    limit: int = Field(default=20, ge=1, le=100)


class DeviceReferenceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # El modelo pasa lo que dijo la persona ("el MacBook"); resolverlo contra
    # los nombres reales es trabajo del servidor, no suyo.
    device: str = Field(min_length=1, max_length=120)


class CreateNoteArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=100_000)


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


async def _list_tasks(user: dict, arguments: BaseModel) -> dict:
    parsed = ListTasksArguments.model_validate(arguments.model_dump())
    found = await asyncio.to_thread(
        db.list_tasks, user["id"], parsed.state, parsed.project, parsed.limit
    )
    return {
        "tasks": [
            {
                "id": task["id"],
                "state": task["estado"],
                "project": Path(task["workspace"]).name if task.get("workspace") else None,
                "model": task.get("modelo"),
                "created_at": task["creado_en"],
                "updated_at": task["actualizado_en"],
                "url": f"/tareas/{task['id']}",
            }
            for task in found
        ]
    }


async def _list_projects(user: dict, _: BaseModel) -> dict:
    projects = await asyncio.to_thread(tasks.listar_proyectos, user["id"])
    return {"projects": projects}


async def _recent_activity(user: dict, arguments: BaseModel) -> dict:
    parsed = RecentActivityArguments.model_validate(arguments.model_dump())
    event_types = activity.CATEGORY_EVENT_TYPES.get(parsed.category, ())
    rows, _ = await asyncio.to_thread(
        db.list_events_for_user, user["id"], parsed.limit, None, event_types
    )
    events = [activity.serialize_event(row, user["id"]) for row in rows]
    return {
        "events": [
            {
                "id": event["id"],
                "type": event["tipo"],
                "category": event["categoria"],
                "title": event["titulo"],
                "detail": event["detalle"],
                "created_at": event["creado_en"],
                "url": event["enlace"],
            }
            for event in events
        ]
    }


def _resolve_device(user: dict, reference: str) -> dict:
    try:
        return nodes.resolve(user["id"], reference)
    except nodes.NodeAmbiguous as error:
        raise InvalidToolArguments(str(error)) from error
    except nodes.NodeNotFound as error:
        raise ToolNotFound(str(error)) from error


def _serialize_device(node: dict) -> dict:
    public = nodes.serialize(node)
    return {
        "id": public["id"],
        "name": public["nombre"],
        "platform": public["plataforma"],
        "online": public["conectado"],
        "capabilities": public["capacidades"],
        "last_seen": public["last_seen"],
    }


async def _list_devices(user: dict, _: BaseModel) -> dict:
    found = await asyncio.to_thread(db.list_nodes, user["id"])
    return {"devices": [_serialize_device(node) for node in found]}


async def _ping_device(user: dict, arguments: BaseModel) -> dict:
    parsed = DeviceReferenceArguments.model_validate(arguments.model_dump())
    node = _resolve_device(user, parsed.device)
    try:
        # Un ping a una máquina apagada no se encola: la respuesta útil es
        # justamente "está apagada", no "ya te contestará mañana".
        outcome = await nodes.dispatch(
            user, node, "ping", queue_if_offline=False
        )
    except nodes.NodeOffline:
        return {"device": _serialize_device(node), "online": False}
    except nodes.NodeError as error:
        raise ToolError(str(error)) from error
    return {
        "device": _serialize_device(node),
        "online": True,
        "state": outcome["estado"],
        "result": outcome.get("resultado"),
    }


async def _list_device_projects(user: dict, arguments: BaseModel) -> dict:
    parsed = DeviceReferenceArguments.model_validate(arguments.model_dump())
    node = _resolve_device(user, parsed.device)
    try:
        outcome = await nodes.dispatch(user, node, "projects.list")
    except nodes.NodeError as error:
        raise ToolError(str(error)) from error
    return {
        "device": _serialize_device(node),
        "state": outcome["estado"],
        "message": outcome.get("mensaje"),
        "result": outcome.get("resultado"),
    }


async def _create_note(user: dict, arguments: BaseModel) -> dict:
    parsed = CreateNoteArguments.model_validate(arguments.model_dump())
    file = await asyncio.to_thread(
        files.create_text_file, user["id"], parsed.name, parsed.content
    )
    serialized = serialize_file(file)
    return {"file": serialized, "files": [serialized]}


PRIMITIVES: dict[str, Primitive] = {
    "system.health": Primitive(
        "system.health", "Estado de Morgana", "Comprueba que Morgana responde.",
        (), (), EmptyArguments, _health,
    ),
    "files.search": Primitive(
        "files.search", "Buscar mis archivos",
        "Enumera o localiza archivos por nombre, ruta o contenido. Úsala cuando "
        "no sea necesario leer el archivo.",
        ("files:read:self",), ("filesystem:read",),
        SearchFilesArguments, _search_files,
    ),
    "files.read": Primitive(
        "files.read", "Leer uno de mis archivos",
        "Localiza directamente un archivo propio y extrae su texto. No necesita "
        "una llamada previa a Buscar mis archivos.",
        ("files:read:self",), ("filesystem:read",),
        ReadFileArguments, _read_file,
    ),
    "files.prepare_download": Primitive(
        "files.prepare_download", "Preparar descarga",
        "Prepara un archivo propio para descargarlo en el dispositivo actual.",
        ("files:read:self",), ("filesystem:read",),
        PrepareDownloadArguments, _prepare_download,
    ),
    "tasks.list": Primitive(
        "tasks.list", "Listar mis tareas",
        "Lista tareas propias y permite filtrar por estado o proyecto.",
        ("tasks:read:self",), ("database:read",),
        ListTasksArguments, _list_tasks,
    ),
    "projects.list": Primitive(
        "projects.list", "Listar mis proyectos",
        "Lista los proyectos disponibles dentro del workspace personal.",
        ("projects:read:self",), ("filesystem:read",),
        EmptyArguments, _list_projects,
    ),
    "activity.recent": Primitive(
        "activity.recent", "Consultar actividad reciente",
        "Consulta la proyección segura de la actividad personal reciente.",
        ("activity:read:self",), ("database:read",),
        RecentActivityArguments, _recent_activity,
    ),
    "devices.list": Primitive(
        "devices.list", "Listar mis dispositivos",
        "Enumera las máquinas propias conectadas a Morgana (PC, portátil) y "
        "dice cuáles están encendidas ahora mismo. Úsala antes de dirigir una "
        "orden a un dispositivo concreto.",
        ("devices:read:self",), ("database:read",),
        EmptyArguments, _list_devices,
    ),
    "devices.ping": Primitive(
        "devices.ping", "Comprobar un dispositivo",
        "Comprueba si una máquina propia está encendida y responde. Acepta el "
        "nombre tal como lo diría la persona, por ejemplo «el MacBook».",
        ("devices:read:self",), ("network:call",),
        DeviceReferenceArguments, _ping_device,
    ),
    "devices.projects": Primitive(
        "devices.projects", "Listar proyectos de un dispositivo",
        "Pide a una máquina propia la lista de proyectos que tiene en local. "
        "Si está apagada, la petición queda pendiente hasta que se encienda.",
        ("devices:read:self",), ("network:call",),
        DeviceReferenceArguments, _list_device_projects,
    ),
    "files.create_note": Primitive(
        "files.create_note", "Crear una nota",
        "Guarda una nota de texto como archivo gestionado del usuario.",
        ("files:write:self",), ("filesystem:write",),
        CreateNoteArguments, _create_note,
    ),
}


@lru_cache(maxsize=None)
def _partial_input_model(input_model: type[BaseModel]) -> type[BaseModel]:
    fields = {}
    for name, field in input_model.model_fields.items():
        definition = field.asdict()
        attributes = {
            key: value
            for key, value in definition["attributes"].items()
            if key not in {"default", "default_factory"}
        }
        annotation = Annotated[
            definition["annotation"],
            *definition["metadata"],
            Field(**attributes),
        ]
        fields[name] = (annotation, None)
    return create_model(
        f"Partial{input_model.__name__}",
        __base__=input_model,
        **fields,
    )


def validate_bound_arguments(primitive: Primitive, arguments: dict) -> dict:
    """Valida solo los presets presentes; la ejecución valida el modelo completo."""
    try:
        parsed = _partial_input_model(primitive.input_model).model_validate(arguments)
    except ValidationError as error:
        raise InvalidToolArguments("Argumentos preconfigurados inválidos") from error
    return parsed.model_dump(exclude_unset=True, by_alias=True)


def _empty_usage() -> dict:
    return {
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "denied": 0,
        "success_rate": None,
        "last_used_at": None,
        "average_duration_ms": None,
    }


def _usage(raw: dict | None) -> dict:
    usage = {**_empty_usage(), **(raw or {})}
    completed = usage["succeeded"] + usage["failed"] + usage["denied"]
    usage["success_rate"] = (
        round(usage["succeeded"] / completed * 100, 1) if completed else None
    )
    return usage


def _system_tool(primitive: Primitive, usage: dict | None = None) -> dict:
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
        "updated_at": None,
        "editable": False,
        "duplicable": True,
        "usage": _usage(usage),
    }


def serialize_custom_tool(
    tool: dict, usage: dict | None = None, editable: bool = False
) -> dict:
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
        "updated_at": tool["updated_at"],
        "editable": editable,
        "duplicable": bool(tool["enabled"]) and primitive is not None,
        "usage": _usage(usage),
    }


def list_catalog(user_id: str, is_admin: bool = False) -> list[dict]:
    usage = db.tool_usage_for_user(user_id)
    catalog = [
        _system_tool(primitive, usage.get(primitive.id))
        for primitive in PRIMITIVES.values()
    ]
    catalog.extend(
        serialize_custom_tool(
            tool,
            usage.get(tool["id"]),
            tool["owner_user_id"] == user_id
            or (tool["scope"] == "lab" and is_admin),
        )
        for tool in db.list_tools_for_user(user_id)
    )
    return catalog


def resolve_catalog_tool(tool_id: str, user_id: str) -> dict | None:
    primitive = PRIMITIVES.get(tool_id)
    if primitive:
        return _system_tool(primitive)
    custom = db.get_tool_for_user(tool_id, user_id)
    return serialize_custom_tool(custom) if custom else None


def _editable_tool(tool_id: str, user: dict) -> dict:
    if tool_id in PRIMITIVES:
        raise ToolPermissionDenied("Las herramientas del sistema no se pueden modificar")
    tool = db.get_tool_for_user(tool_id, user["id"])
    if not tool:
        raise ToolNotFound("Herramienta no encontrada")
    if tool["scope"] == "lab" and not bool(user.get("is_admin")):
        raise ToolPermissionDenied(
            "Solo un administrador puede modificar herramientas del lab"
        )
    if tool["scope"] == "personal" and tool["owner_user_id"] != user["id"]:
        raise ToolNotFound("Herramienta no encontrada")
    return tool


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
    validated_arguments = validate_bound_arguments(primitive, bound_arguments)
    tool = db.create_tool(
        scope,
        user["id"] if scope == "personal" else None,
        name.strip(),
        description.strip(),
        primitive_id,
        validated_arguments,
        source,
    )
    return serialize_custom_tool(tool, editable=True)


def update_custom_tool(
    tool_id: str,
    user: dict,
    name: str,
    description: str,
    primitive_id: str,
    scope: str,
    bound_arguments: dict,
) -> dict:
    _editable_tool(tool_id, user)
    primitive = PRIMITIVES.get(primitive_id)
    if not primitive:
        raise ToolNotFound("La capacidad base no existe")
    if scope == "lab" and not bool(user.get("is_admin")):
        raise ToolPermissionDenied(
            "Solo un administrador puede publicar herramientas del lab"
        )
    validated_arguments = validate_bound_arguments(primitive, bound_arguments)
    updated = db.update_tool(
        tool_id,
        scope,
        user["id"] if scope == "personal" else None,
        name.strip(),
        description.strip(),
        primitive_id,
        validated_arguments,
    )
    if not updated:
        raise ToolNotFound("Herramienta no encontrada")
    return serialize_custom_tool(updated, editable=True)


def set_enabled(tool_id: str, user: dict, enabled: bool) -> dict:
    tool = _editable_tool(tool_id, user)
    updated = db.set_tool_enabled_by_id(tool["id"], enabled)
    if not updated:
        raise ToolNotFound("Herramienta no encontrada")
    return serialize_custom_tool(updated, editable=True)


def duplicate_tool(tool_id: str, user: dict) -> dict:
    source = resolve_catalog_tool(tool_id, user["id"])
    if not source:
        raise ToolNotFound("Herramienta no encontrada")
    if not source["enabled"]:
        raise ToolDisabled("La herramienta está desactivada")
    copied_name = f"{source['name'][:112].rstrip()} (copia)"
    return create_custom_tool(
        user,
        copied_name,
        source["description"],
        source["primitive_id"],
        "personal",
        source.get("bound_arguments", {}),
    )


def list_invocations(tool_id: str, user: dict, limit: int = 25) -> list[dict]:
    if not resolve_catalog_tool(tool_id, user["id"]):
        raise ToolNotFound("Herramienta no encontrada")
    return db.list_tool_invocations(tool_id, user["id"], limit)


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
        db.log_event(
            "tool_invocation_denied",
            user["id"],
            tool_id=audit_id,
            error_code="invalid_arguments",
        )
        raise InvalidToolArguments("Argumentos inválidos") from error
    except Exception:
        db.finish_tool_invocation(invocation_id, "failed", started_at, "execution_failed")
        db.log_event(
            "tool_invocation_failed",
            user["id"],
            tool_id=audit_id,
            error_code="execution_failed",
        )
        raise
    db.finish_tool_invocation(invocation_id, "succeeded", started_at)
    db.log_event("tool_invocation_succeeded", user["id"], tool_id=audit_id)
    return {
        "invocation_id": invocation_id,
        "tool_id": audit_id,
        "status": "succeeded",
        "result": result,
    }

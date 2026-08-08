"""Las capacidades de Morgana, servidas a `agy` por MCP.

El motor Antigravity no comparte las tools del SDK de Claude: `agy` es un
proceso aparte y solo sabe hablar MCP. Este módulo es el puente.

**Ejecuta delegando en Morgana por HTTP, no por su cuenta.** Es la parte que
importa entender: `agy` lanza este servidor como un proceso suyo, y ahí dentro
no existe el estado vivo del servidor —qué máquinas están conectadas vive en
memoria de uvicorn, igual que los WebSockets por los que se les manda algo—.
Ejecutando en local, todas las tools de `devices` y `media` verían el mundo
apagado y no podrían mandar nada. Llamando al endpoint, el trabajo ocurre donde
tiene que ocurrir y de paso pasa por la validación, la auditoría y el régimen
de aprobaciones de siempre.

Los identificadores llevan punto (`files.search`) y aquí viajan con guion bajo
(`files_search`), que es lo que aceptan sin discusión los clientes MCP.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
log = logging.getLogger("morgana.agy_mcp")

# El servidor lo lanza `agy` desde su propio directorio, así que el paquete
# puede no estar en el path.
sys.path.insert(0, os.environ.get("MORGANA_ROOT", "/srv/morgana"))

import httpx  # noqa: E402

from app import tools  # noqa: E402

VARIABLE_TOKEN = "MORGANA_TOKEN"
VARIABLE_URL = "MORGANA_URL"
URL_POR_DEFECTO = "http://127.0.0.1:8000"
# Una orden a otra máquina puede tardar: el servidor ya tiene sus propios
# topes, así que aquí solo hace falta no cortar antes que él.
TIMEOUT = 120.0


def nombre_mcp(tool_id: str) -> str:
    return tool_id.replace(".", "_")


def id_primitiva(nombre: str) -> str:
    """Deshace el cambio de nombre, sin fiarse de lo que llegue de fuera."""
    for tool_id in tools.PRIMITIVES:
        if nombre_mcp(tool_id) == nombre:
            return tool_id
    raise tools.ToolNotFound(f"Morgana no tiene ninguna capacidad «{nombre}»")


def _descripcion(primitive: tools.Primitive) -> str:
    """La descripción de la primitiva, con sus efectos si los tiene.

    Que el modelo sepa de antemano que algo escribe o sale a la red le ayuda a
    no usarlo por descuido, y a avisarte antes de hacerlo.
    """
    if not primitive.effects:
        return primitive.description
    return f"{primitive.description} (efectos: {', '.join(primitive.effects)})"


async def ejecutar(tool_id: str, arguments: dict) -> dict:
    """Le pide a Morgana que ejecute la capacidad, y devuelve lo que conteste."""
    token = os.environ.get(VARIABLE_TOKEN, "").strip()
    if not token:
        return {"error": f"Falta {VARIABLE_TOKEN}: no sé de parte de quién voy"}
    base = os.environ.get(VARIABLE_URL, "").strip() or URL_POR_DEFECTO

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as cliente:
            respuesta = await cliente.post(
                f"{base}/api/herramientas/{tool_id}/ejecutar",
                json={"arguments": arguments},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as error:
        return {"error": f"No se pudo hablar con Morgana: {error}", "tool": tool_id}

    if respuesta.status_code != 200:
        # Un rechazo es una respuesta legítima —argumentos malos, capacidad
        # apagada—, no una caída: el modelo tiene que poder leerlo y corregir.
        try:
            detalle = respuesta.json().get("error", respuesta.text)
        except ValueError:
            detalle = respuesta.text[:300]
        return {"error": detalle, "tool": tool_id, "status": respuesta.status_code}

    return respuesta.json()


def construir_servidor():
    from mcp.server.lowlevel import Server  # noqa: PLC0415
    import mcp.types as types  # noqa: PLC0415

    server = Server("morgana")

    @server.list_tools()
    async def listar() -> list:
        return [
            types.Tool(
                name=nombre_mcp(tool_id),
                description=_descripcion(primitive),
                inputSchema=primitive.input_model.model_json_schema(),
            )
            for tool_id, primitive in tools.PRIMITIVES.items()
        ]

    @server.call_tool()
    async def llamar(name: str, arguments: dict | None) -> list:
        try:
            tool_id = id_primitiva(name)
        except tools.ToolNotFound as error:
            resultado = {"error": str(error)}
        else:
            resultado = await ejecutar(tool_id, arguments or {})
        return [
            types.TextContent(
                type="text",
                text=json.dumps(resultado, ensure_ascii=False, default=str),
            )
        ]

    return server


async def _servir() -> None:
    from mcp.server.stdio import stdio_server  # noqa: PLC0415

    server = construir_servidor()
    log.info("Servidor MCP de Morgana en pie")
    async with stdio_server() as (lectura, escritura):
        await server.run(lectura, escritura, server.create_initialization_options())


def main() -> None:
    asyncio.run(_servir())


if __name__ == "__main__":
    main()

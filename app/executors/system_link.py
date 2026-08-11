"""Levantar el ordenador del usuario y decir por dónde se le habla.

Vive aparte de los dos motores porque no es de ninguno: `agy` y Claude Code
necesitan lo mismo —que el servidor MCP del nodo esté en pie y con qué URL
alcanzarlo—, y duplicarlo era garantizar que un día uno de los dos se quedara
atrás.

La URL se compone aquí y no en el nodo por una razón concreta: el agente sabe
qué ruta sirve, incluido el secreto que le puso dentro, pero no con qué nombre
le ve el contenedor. Eso solo lo sabe el servidor.
"""
from __future__ import annotations

import logging

from ..config import settings

log = logging.getLogger("vibi.system_link")


async def asegurar_sistema(user: dict) -> str:
    """Enciende el servidor del ordenador y devuelve su URL, o cadena vacía.

    Vacío no es una excepción: que no haya ningún dispositivo conectado, o que
    lo tengas con la ejecución remota apagada, son estados normales. En ellos
    Vibi conversa igual, solo que sin ordenador debajo.
    """
    if not settings.system_mcp_enabled:
        return ""

    from .. import nodes, tools  # noqa: PLC0415 - perezoso para no cerrar un ciclo

    try:
        node = tools.resolve_device(user, settings.system_mcp_device)
    except tools.ToolError as error:
        log.info("Sin ordenador que servir: %s", error)
        return ""

    try:
        # No se encola: un servidor que se levantara dentro de seis horas, la
        # próxima vez que enciendas el PC, no le sirve a la sesión de ahora.
        resultado = await nodes.dispatch(
            user,
            node,
            "system.mcp",
            {
                "accion": "arrancar",
                "puerto": settings.system_mcp_port,
                "bind": settings.system_mcp_bind,
            },
            queue_if_offline=False,
        )
    except nodes.NodeError as error:
        log.info("Sin ordenador que servir: %s", error)
        return ""

    salida = resultado.get("resultado") or {}
    if resultado.get("estado") != "ok" or not salida.get("ruta"):
        log.warning(
            "El nodo %s no pudo servir su disco: %s",
            node["nombre"],
            salida.get("error") or resultado.get("mensaje") or resultado.get("estado"),
        )
        return ""

    puerto = salida.get("puerto") or settings.system_mcp_port
    # La ruta trae el secreto dentro, así que la URL entera no se registra.
    log.info("Disco de %s servido en el puerto %s", node["nombre"], puerto)
    return f"http://{settings.system_mcp_host}:{puerto}{salida['ruta']}"

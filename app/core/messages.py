"""Procesamiento de mensajes independiente del canal de entrada."""
from dataclasses import dataclass
from typing import Literal

from .. import db, router, tasks
from ..claude_models import ClaudeModel, DEFAULT_CLAUDE_MODEL
from ..executors import groq_chat

ORIGEN_POR_CANAL = {
    "pwa": "pwa",
    "telegram": "telegram",
    "cara": "cara",
}


@dataclass(frozen=True)
class ResultadoMensaje:
    via: Literal["rapida", "agentica"]
    respuesta: str | None = None
    task: dict | None = None
    resolucion: tasks.ResolucionProyecto | None = None


async def procesar_encargo(
    user: dict,
    prompt: str,
    proyecto: str | None,
    canal: str,
    modelo: ClaudeModel = DEFAULT_CLAUDE_MODEL,
) -> ResultadoMensaje:
    resolucion = tasks.resolver_proyecto(user["id"], proyecto)
    if resolucion.estado != "ok":
        return ResultadoMensaje("agentica", resolucion=resolucion)

    task = await tasks.encolar_tarea(
        user["id"], user["nombre"], prompt, resolucion.workspace, modelo
    )
    db.log_event(
        "proyecto_seleccionado",
        user["id"],
        task_id=task["id"],
        proyecto=proyecto,
        canal=canal,
    )
    return ResultadoMensaje("agentica", task=task, resolucion=resolucion)


async def procesar_mensaje(
    user: dict,
    texto: str,
    canal: str,
    modelo: ClaudeModel = DEFAULT_CLAUDE_MODEL,
    client_ref: str | None = None,
) -> ResultadoMensaje:
    clasificacion = await router.clasificar(texto)
    via = clasificacion["via"]
    proyecto = clasificacion["proyecto"]
    db.log_event(
        "mensaje", user["id"], via=via, proyecto=proyecto, canal=canal
    )

    if via == "rapida":
        origen = ORIGEN_POR_CANAL.get(canal)
        if not origen:
            raise ValueError(f"Canal de conversación no soportado: {canal}")
        respuesta = await groq_chat.responder(
            user["id"], user["nombre"], texto, origen, client_ref
        )
        return ResultadoMensaje("rapida", respuesta=respuesta)

    return await procesar_encargo(user, texto, proyecto, canal, modelo)

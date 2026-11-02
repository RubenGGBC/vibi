"""Las órdenes que la voz le da al móvil.

El móvil es un nodo: la orden sale por `nodes.dispatch`, queda en Actividad y
vuelve con el resultado real. Lo único distinto es que aquí nada se encola. Una
«pausa» de hace una hora no debe parar la música ahora, así que si el móvil no
está, la orden falla y se le cuenta al usuario.
"""
from __future__ import annotations

import logging

from . import db, nodes

log = logging.getLogger(__name__)

_MUSICA = {"pausar", "reanudar", "siguiente", "anterior", "avanzar", "que_suena"}
_VOLUMEN = {"leer", "poner", "subir", "bajar"}
_NOTIFICACIONES = {"listar", "descartar", "pulsar", "responder"}
_PANTALLA = {"tocar", "escribir", "deslizar", "atras", "inicio", "recientes"}


def capacidad_para(herramienta: str, argumentos: dict) -> str:
    """La capacidad del nodo que atiende una herramienta de voz."""
    accion = argumentos.get("accion")
    if herramienta == "movil_musica":
        if accion == "reproducir":
            return "movil.media.reproducir"
        if accion in _MUSICA:
            return "movil.media"
    elif herramienta == "movil_volumen":
        if accion in _VOLUMEN:
            return "movil.volumen"
    elif herramienta == "movil_notificaciones":
        if accion in _NOTIFICACIONES:
            return f"movil.notificaciones.{accion}"
    elif herramienta == "movil_abrir":
        return "movil.apps.abrir"
    elif herramienta == "movil_pantalla":
        if accion == "leer":
            return "movil.pantalla.leer"
        if accion in _PANTALLA:
            return "movil.pantalla.actuar"
    else:
        raise ValueError(f"No conozco la herramienta {herramienta}")
    raise ValueError(f"{herramienta} no sabe hacer «{accion}»")


def nodos_moviles(user_id: str) -> list[dict]:
    return [
        node
        for node in db.list_nodes(user_id)
        if node["estado"] == "activo" and nodes.es_movil(node)
    ]


def tiene_movil(user_id: str) -> bool:
    return bool(nodos_moviles(user_id))


def _elegir_movil(user_id: str) -> dict | None:
    moviles = nodos_moviles(user_id)
    conectados = [node for node in moviles if nodes.manager.is_online(node["id"])]
    return (conectados or moviles or [None])[0]


def _resolver(respuesta: dict) -> dict:
    """Solo `ok` es un éxito: lo demás se cuenta como error, nunca se disimula."""
    estado = respuesta.get("estado")
    resultado = respuesta.get("resultado")
    if estado == "ok":
        return resultado if isinstance(resultado, dict) else {"ok": True}
    if estado == "error":
        if isinstance(resultado, dict) and resultado.get("error"):
            return resultado
        return {"error": "El móvil no ha podido hacerlo."}
    if estado == "timeout":
        return {"error": "El móvil no ha contestado a tiempo."}
    return {"error": respuesta.get("mensaje") or "El móvil no está conectado."}


async def _dispatch(user: dict, node: dict, capacidad: str, argumentos: dict) -> dict:
    try:
        respuesta = await nodes.dispatch(
            user, node, capacidad, argumentos, queue_if_offline=False
        )
    except nodes.NodeError as error:
        return {"error": str(error)}
    return _resolver(respuesta)


async def ejecutar(user: dict, herramienta: str, argumentos: dict) -> dict:
    """Ejecuta una herramienta de voz en el móvil y devuelve su resultado real."""
    if not isinstance(argumentos, dict):
        return {"error": "Argumentos no válidos"}
    try:
        capacidad = capacidad_para(herramienta, argumentos)
    except ValueError as error:
        return {"error": str(error)}
    node = _elegir_movil(user["id"])
    if not node:
        return {"error": "No tienes ningún móvil conectado a Vibi."}
    return await _dispatch(user, node, capacidad, argumentos)

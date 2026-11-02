"""Las órdenes que la voz le da al móvil.

El móvil es un nodo: la orden sale por `nodes.dispatch`, queda en Actividad y
vuelve con el resultado real. Lo único distinto es que aquí nada se encola. Una
«pausa» de hace una hora no debe parar la música ahora, así que si el móvil no
está, la orden falla y se le cuenta al usuario.
"""
from __future__ import annotations

import asyncio
import logging

from . import db, nodes

log = logging.getLogger(__name__)

# En una conversación nadie espera 45 s. Poner una canción tarda más porque el móvil
# comprueba que de verdad ha cambiado.
PLAZO_ORDEN_S = 10.0
PLAZO_REPRODUCIR_S = 15.0

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
    plazo = PLAZO_REPRODUCIR_S if capacidad == "movil.media.reproducir" else PLAZO_ORDEN_S
    try:
        respuesta = await nodes.dispatch(
            user,
            node,
            capacidad,
            argumentos,
            queue_if_offline=False,
            plazo_segundos=plazo,
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
    if capacidad == "movil.media.reproducir":
        return await _reproducir(user, node, argumentos)
    return await _dispatch(user, node, capacidad, argumentos)


def _buscar_cancion(consulta: str) -> str | None:
    """El ID de la primera canción. `ytmusicapi` no es oficial y se puede romper."""
    from ytmusicapi import YTMusic

    for resultado in YTMusic().search(consulta, filter="songs", limit=5):
        if resultado.get("videoId"):
            return resultado["videoId"]
    return None


async def _reproducir(user: dict, node: dict, argumentos: dict) -> dict:
    """Primero se lo pide a la app; si no sabe buscar, busca aquí y le da el ID."""
    consulta = str(argumentos.get("consulta") or "").strip()
    if not consulta:
        return {"error": "No me has dicho qué canción poner."}
    directa = await _dispatch(user, node, "movil.media.reproducir", {"consulta": consulta})
    if directa.get("codigo") != "no_soportado":
        return directa
    try:
        video_id = await asyncio.to_thread(_buscar_cancion, consulta)
    except Exception as error:  # noqa: BLE001 - una librería no oficial falla de muchas formas
        log.warning("No se pudo buscar la canción: %s", error)
        return {"error": "No he podido buscar esa canción."}
    if not video_id:
        return {"error": f"No he encontrado «{consulta}»."}
    return await _dispatch(user, node, "movil.media.reproducir", {"video_id": video_id})


async def notificar_movil(
    user_id: str, texto: str, task_id: str | None = None, acciones: bool = False
) -> None:
    """Avisa al móvil de lo que ha terminado, sin hablar sin que se lo pidan."""
    for node in nodos_moviles(user_id):
        await nodes.manager.send(
            node["id"], {"tipo": "notificacion", "texto": texto, "task_id": task_id}
        )

"""Conexión persistente del nodo con Vibi.

El agente siempre marca hacia fuera y se reconecta solo. Nunca escucha en un
puerto: no hay nada que abrir en el router ni que exponer a la red.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random

import websockets
from websockets.exceptions import InvalidStatus, WebSocketException

from . import app_catalog, avisos, capabilities, relevo, system_shell, vigilancias
from .config import NodeConfig, websocket_url

log = logging.getLogger("vibi.node")

PING_INTERVAL = 60.0
MAX_BACKOFF = 60.0

# Sobrevive a las reconexiones del WebSocket dentro del mismo proceso. Así un
# trabajo terminado no se anuncia otra vez cada vez que vuelve la red.
_trabajos_notificados: set[str] = set()


async def _vigilar_trabajo(connection, trabajo_id: str) -> None:
    """Sigue un trabajo propio hasta su final y lo anuncia una sola vez."""
    posicion = 0
    while True:
        try:
            estado = await asyncio.to_thread(
                system_shell.salida, trabajo_id, posicion
            )
        except system_shell.ErrorShell:
            return
        posicion = int(estado.get("posicion") or posicion)
        if estado.get("terminado"):
            await connection.send(
                json.dumps(
                    {
                        "tipo": "trabajo",
                        "trabajo": trabajo_id,
                        "comando": estado.get("comando"),
                        "codigo": estado.get("codigo"),
                        "salida": str(estado.get("salida") or "")[-4000:],
                        "segundos": estado.get("segundos"),
                    }
                )
            )
            _trabajos_notificados.add(trabajo_id)
            return
        await asyncio.sleep(2.0)


async def _ejecutar_orden(
    connection, config: NodeConfig, orden: dict, seguir_trabajo=None
) -> None:
    order_id = orden.get("id")
    capability = str(orden.get("capability", ""))
    arguments = orden.get("arguments") or {}
    log.info("Orden %s: %s", order_id, capability)

    try:
        # Las capacidades son síncronas y tocan disco: fuera del bucle de
        # eventos para que el nodo siga respondiendo mientras trabajan.
        resultado = await asyncio.to_thread(
            capabilities.run, config, capability, arguments
        )
        estado = "ok"
    except capabilities.CapabilityError as error:
        estado, resultado = "error", {"error": str(error)}
    except Exception as error:  # noqa: BLE001 - un fallo local no tumba el agente
        log.exception("Orden %s fallida", order_id)
        estado, resultado = "error", {"error": f"{type(error).__name__}: {error}"}

    await connection.send(
        json.dumps(
            {
                "tipo": "resultado",
                "id": order_id,
                "estado": estado,
                "resultado": resultado,
            }
        )
    )
    if (
        estado == "ok"
        and isinstance(resultado, dict)
        and resultado.get("terminado") is False
        and resultado.get("trabajo")
        and seguir_trabajo is not None
    ):
        seguir_trabajo(str(resultado["trabajo"]))


async def _keepalive(connection) -> None:
    while True:
        await asyncio.sleep(PING_INTERVAL)
        await connection.send(json.dumps({"tipo": "ping"}))


async def _sesion(config: NodeConfig) -> None:
    url = websocket_url(config.url)
    async with websockets.connect(url, max_size=2**20) as connection:
        await connection.send(
            json.dumps(
                {
                    "tipo": "hola",
                    "token": config.token,
                    "capacidades": capabilities.disponibles(),
                }
            )
        )
        saludo = json.loads(await connection.recv())
        if saludo.get("tipo") != "conexion_lista":
            raise RuntimeError(f"Vibi rechazó la conexión: {saludo}")
        log.info("Conectado a Vibi como «%s»", saludo.get("nombre"))

        keepalive = asyncio.create_task(_keepalive(connection))
        # Lo único que el nodo dice sin que le pregunten. Se ata a la sesión: si
        # la conexión cae, deja de mirar hasta que haya otra, y así no acumula
        # avisos para soltarlos todos de golpe al reconectar.
        vigilante = asyncio.create_task(avisos.vigilar(connection, config))
        # Lo segundo que dice solo. Los encargos llegan del servidor y se
        # reponen enteros en cada mensaje, así que arrancar con la lista vacía
        # es lo correcto: la primera suscripción llega justo tras el saludo.
        encargos = vigilancias.Encargos()
        centinela = asyncio.create_task(
            vigilancias.vigilar(connection, config, encargos)
        )
        tareas: set[asyncio.Task] = set()
        monitores: dict[str, asyncio.Task] = {}

        def seguir_trabajo(trabajo_id: str) -> None:
            if trabajo_id in _trabajos_notificados or trabajo_id in monitores:
                return
            tarea = asyncio.create_task(_vigilar_trabajo(connection, trabajo_id))
            monitores[trabajo_id] = tarea
            tarea.add_done_callback(lambda _t, job=trabajo_id: monitores.pop(job, None))

        # Una caída de red no convierte el trabajo en huérfano. Al reconectar
        # se reconcilia el registro entero y se retoma lo que no se anunció.
        inventario_trabajos = await asyncio.to_thread(system_shell.trabajos)
        for trabajo in inventario_trabajos.get("trabajos", []):
            if trabajo.get("seguimiento") and not trabajo.get("terminado"):
                seguir_trabajo(str(trabajo.get("trabajo") or ""))

        async def descubrir_trabajos() -> None:
            """Incorpora también los que nacen por el MCP directo de `agy`."""
            while True:
                inventario = await asyncio.to_thread(system_shell.trabajos)
                for trabajo in inventario.get("trabajos", []):
                    if trabajo.get("seguimiento") and not trabajo.get("terminado"):
                        seguir_trabajo(str(trabajo.get("trabajo") or ""))
                await asyncio.sleep(2.0)

        radar_trabajos = asyncio.create_task(descubrir_trabajos())
        try:
            async for raw in connection:
                mensaje = json.loads(raw)
                tipo = mensaje.get("tipo")
                if tipo == "vigilancias":
                    encargos.reemplazar(mensaje.get("vigilancias"))
                    log.info("Ahora vigilo %d cosas", len(encargos))
                    continue
                if tipo != "orden":
                    continue
                tarea = asyncio.create_task(
                    _ejecutar_orden(connection, config, mensaje, seguir_trabajo)
                )
                tareas.add(tarea)
                tarea.add_done_callback(tareas.discard)
        finally:
            keepalive.cancel()
            vigilante.cancel()
            centinela.cancel()
            radar_trabajos.cancel()
            for tarea in tareas:
                tarea.cancel()
            for tarea in monitores.values():
                tarea.cancel()


async def run_forever(config: NodeConfig) -> None:
    """Mantiene el nodo conectado, con espera creciente entre reintentos."""
    # Construir el inventario puede tocar registro y menú Inicio. El catálogo
    # se ocupa de hacerlo en un hilo y esta llamada vuelve antes de conectar.
    app_catalog.catalog.start_background()
    relevo.iniciar()
    backoff = 1.0
    while True:
        try:
            await _sesion(config)
            backoff = 1.0
        except InvalidStatus as error:
            log.error("Vibi rechazó la conexión: %s", error)
        except (OSError, WebSocketException) as error:
            log.warning("Sin conexión con Vibi (%s); reintento", error)
        except RuntimeError as error:
            # Token revocado o inválido: reintentar en bucle cerrado no arregla
            # nada, pero tampoco queremos que el servicio muera en silencio.
            log.error("%s", error)

        espera = min(backoff, MAX_BACKOFF) * (0.5 + random.random())
        await asyncio.sleep(espera)
        backoff = min(backoff * 2, MAX_BACKOFF)

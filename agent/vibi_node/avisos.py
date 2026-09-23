"""Contarle a Vibi lo que este ordenador te está notificando.

`notifications_windows` y `notifications_macos` saben leer el centro de
notificaciones de su sistema; esto es lo que elige uno y convierte lo que lea en
algo que llega al servidor. Es **lo primero que el nodo dice
por su cuenta**: hasta ahora solo hablaba cuando le preguntaban —recibía una
orden y devolvía un resultado— y todo lo demás del protocolo sigue así.

Por eso el mensaje va aparte y no como un `resultado` sin orden que lo pida: el
servidor distingue lo que contestó a algo de lo que llegó solo, y un nodo que
empieza a hablar sin que nadie le pregunte tiene que verse en el protocolo.

**Se calla al arrancar.** El primer vistazo al centro de notificaciones trae lo
que lleve ahí desde ayer, y eso no es noticia. De eso se ocupa el `Vigia`.

Aquí no se decide **nada** sobre si un aviso merece la pena. El nodo cuenta lo
que ve y el servidor filtra: las reglas de silencio son del usuario, viven en
su base de datos y valen para todos sus equipos. Meterlas aquí sería tenerlas
repetidas en cada ordenador y desincronizadas al día siguiente.
"""
from __future__ import annotations

import asyncio
import json
import logging
import platform
from dataclasses import asdict

from .config import NodeConfig
from .notifications_comun import (  # noqa: F401 - `Aviso` la usan las pruebas
    Aviso,
    ErrorNotificaciones,
    Vigia,
)

log = logging.getLogger("vibi.node.avisos")

# Cuánto se espera entre vistazos. La lectura en sí ya tarda medio segundo y no
# consume CPU, así que esto solo gradúa cuánto puede tardar en llegarte un
# aviso: con 1,5 s, como mucho dos segundos.
INTERVALO = 1.5

# Cuánto se espera tras un fallo de lectura antes de volver a intentarlo. Más
# largo que el intervalo normal: si Windows está negándose, insistir cada
# segundo y medio no lo arregla y llena el log.
ESPERA_TRAS_FALLO = 30.0


def _lector():
    """El módulo que sabe leer las notificaciones de este ordenador, o nada.

    Cada sistema lo hace de una forma que no se parece en nada al otro: Windows
    presta `UserNotificationListener`, y macOS no presta nada —hay que leerle
    por detrás la base de datos de `usernoted`—. Lo único que comparten es la
    forma del resultado, que vive en `notifications_comun`.

    Se importa aquí dentro y no arriba para que un Mac no cargue WinRT ni un PC
    intente hablar con Spotlight. Y se resuelve en cada llamada, no una vez al
    importar, porque así se puede probar sin estar en el sistema de turno.
    """
    sistema = platform.system()
    if sistema == "Windows":
        from . import notifications_windows  # noqa: PLC0415 - solo en Windows

        return notifications_windows
    if sistema == "Darwin":
        from . import notifications_macos  # noqa: PLC0415 - solo en macOS

        return notifications_macos
    return None


def disponible() -> bool:
    """Si este equipo puede leer sus notificaciones ahora mismo."""
    lector = _lector()
    return bool(lector and lector.disponible())


def _leer():
    lector = _lector()
    if lector is None:
        raise ErrorNotificaciones("Este ordenador no sabe leer sus notificaciones")
    return lector.leer()


def _vigia():
    return Vigia()


async def vigilar(connection, config: NodeConfig) -> None:
    """Mira el centro de notificaciones y manda lo nuevo, hasta que lo corten.

    Si este equipo no puede leerlas —no hay lector para su sistema, o el
    usuario no ha dado el permiso— la tarea se retira en vez de quedarse dando
    vueltas en balde.
    """
    if not disponible():
        # Con la ayuda dentro: un «no vigilo» a secas es lo que hace que esto se
        # descubra semanas después, cuando alguien echa de menos un aviso. Y la
        # ayuda la pone el lector, porque «qué permiso falta» es cosa suya:
        # `avisos` no tiene por qué saber cómo se llama en cada sistema.
        lector = _lector()
        if lector is None:
            log.info(
                "%s no sabe leer su centro de notificaciones; no vigilo",
                platform.system() or "Este sistema",
            )
        else:
            log.info(
                "No puedo leer las notificaciones; no vigilo. %s",
                lector.AYUDA_PERMISO,
            )
        return

    vigia = _vigia()
    while True:
        try:
            nuevas = vigia.novedades(await asyncio.to_thread(_leer))
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - un fallo no calla al nodo
            log.warning("No pude leer las notificaciones: %s", error)
            await asyncio.sleep(ESPERA_TRAS_FALLO)
            continue

        for aviso in nuevas:
            try:
                await connection.send(
                    json.dumps({"tipo": "aviso", "aviso": asdict(aviso)})
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                # La conexión se ha caído: quien la gestiona ya se encarga de
                # reconectar, y este bucle morirá con la sesión.
                log.warning("No pude mandar un aviso: %s", error)
                return

        await asyncio.sleep(INTERVALO)

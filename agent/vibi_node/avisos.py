"""Contarle a Vibi lo que este ordenador te está notificando.

`notifications_windows` sabe leer el centro de notificaciones; esto es lo que
lo convierte en algo que llega al servidor. Es **lo primero que el nodo dice
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

log = logging.getLogger("vibi.node.avisos")

# Cuánto se espera entre vistazos. La lectura en sí ya tarda medio segundo y no
# consume CPU, así que esto solo gradúa cuánto puede tardar en llegarte un
# aviso: con 1,5 s, como mucho dos segundos.
INTERVALO = 1.5

# Cuánto se espera tras un fallo de lectura antes de volver a intentarlo. Más
# largo que el intervalo normal: si Windows está negándose, insistir cada
# segundo y medio no lo arregla y llena el log.
ESPERA_TRAS_FALLO = 30.0


def _plataforma_soportada() -> bool:
    return platform.system() == "Windows"


# Se importan de forma perezosa y se exponen aquí para que las pruebas puedan
# sustituirlos sin cargar WinRT, y para que un Mac no reviente al importar.

def disponible() -> bool:
    """Si este equipo puede leer sus notificaciones ahora mismo."""
    if not _plataforma_soportada():
        return False
    from . import notifications_windows  # noqa: PLC0415 - solo en Windows

    return notifications_windows.disponible()


def _leer():
    from . import notifications_windows  # noqa: PLC0415 - solo en Windows

    return notifications_windows.leer()


def _vigia():
    from . import notifications_windows  # noqa: PLC0415 - solo en Windows

    return notifications_windows.Vigia()


class Aviso:
    """Alias del tipo que devuelve el lector, para no importarlo en cadena."""

    def __new__(cls, **campos):
        from . import notifications_windows  # noqa: PLC0415

        return notifications_windows.Aviso(**campos)


async def vigilar(connection, config: NodeConfig) -> None:
    """Mira el centro de notificaciones y manda lo nuevo, hasta que lo corten.

    Si este equipo no puede leerlas —no es Windows, o el usuario no ha dado
    permiso— la tarea se retira en vez de quedarse dando vueltas en balde.
    """
    if not disponible():
        log.info("Sin lectura de notificaciones en este equipo; no vigilo")
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

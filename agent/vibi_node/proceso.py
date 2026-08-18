"""Lanzar procesos sin que Windows abra una consola sobre lo que estés haciendo.

Cada `subprocess` de un programa sin consola propia —y el agente lo es— hace
que Windows cree una ventana negra. Da igual que dure 40 ms: parpadea encima de
lo que tengas delante y te roba el foco. Como Vibi mira la pantalla, lee
ventanas y ejecuta órdenes constantemente, eso son decenas de parpadeos por
conversación.

`CREATE_NO_WINDOW` solo afecta a la consola del proceso que lanzamos: una
aplicación con interfaz propia —abrir Spotify -- sigue apareciendo como debe.
"""
from __future__ import annotations

import subprocess
import sys


def sin_ventana() -> dict:
    """Los `kwargs` que hay que añadirle a `run` o `Popen`. Vacío fuera de Windows."""
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def sin_ventana_en_grupo() -> dict:
    """Igual, para lo que además tiene que sobrevivir a un Ctrl-C nuestro.

    `CREATE_NEW_PROCESS_GROUP` saca al hijo de nuestro grupo de consola, que es
    lo que quieren los servidores de larga vida: que una señal dirigida al
    agente no se los lleve por delante.
    """
    if sys.platform != "win32":
        return {}
    return {
        "creationflags": (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    }

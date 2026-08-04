"""Lo que este nodo sabe hacer.

El agente solo ejecuta capacidades de este diccionario. Aunque el servidor
pidiera otra cosa, aquí no hay forma de llegar a shell: cada capacidad es una
función concreta escrita a mano.
"""
from __future__ import annotations

import platform
import socket
import time
from pathlib import Path

from .config import NodeConfig

MAX_PROJECTS = 200


class CapabilityError(Exception):
    pass


def _ping(config: NodeConfig, _: dict) -> dict:
    return {
        "hostname": socket.gethostname(),
        "plataforma": f"{platform.system()} {platform.release()}",
        "nodo": config.nombre,
        "hora": time.time(),
    }


def _list_projects(config: NodeConfig, _: dict) -> dict:
    root = Path(config.projects_root).expanduser()
    if not root.is_dir():
        raise CapabilityError(
            f"La carpeta de proyectos configurada no existe: {root}"
        )

    proyectos = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        proyectos.append(
            {
                "nombre": entry.name,
                "git": (entry / ".git").exists(),
                "modificado_en": entry.stat().st_mtime,
            }
        )
        if len(proyectos) >= MAX_PROJECTS:
            break

    # La ruta absoluta se queda en la máquina: al servidor solo van nombres.
    return {"proyectos": proyectos, "total": len(proyectos)}


HANDLERS = {
    "ping": _ping,
    "projects.list": _list_projects,
}


def run(config: NodeConfig, capability: str, arguments: dict) -> dict:
    handler = HANDLERS.get(capability)
    if handler is None:
        raise CapabilityError(f"Este dispositivo no sabe hacer «{capability}»")
    return handler(config, arguments or {})

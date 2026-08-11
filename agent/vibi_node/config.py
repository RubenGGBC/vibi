"""Credencial local del nodo.

Lo único que se guarda en la máquina es el token de este nodo: la contraseña
de Vibi se usa una vez, en el alta, y no se escribe nunca en disco.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import stat
from dataclasses import dataclass, asdict
from pathlib import Path

CONFIG_DIR = Path.home() / ".vibi"
CONFIG_PATH = CONFIG_DIR / "node.json"
LEGACY_CONFIG_PATH = Path.home() / ".morgana" / "node.json"


def environment_value(current: str, legacy: str, default: str = "") -> str:
    """Lee primero el nombre canónico y conserva el anterior como fallback."""
    return os.environ.get(current, os.environ.get(legacy, default))


def compatible_path(current: Path, legacy: Path) -> Path:
    """Prefiere la ruta nueva y reutiliza la antigua si aún es la única."""
    if current.exists() or not legacy.exists():
        return current
    return legacy


@dataclass(frozen=True)
class NodeConfig:
    url: str
    node_id: str
    token: str
    nombre: str
    projects_root: str
    # Dónde aterriza lo que llega de otro dispositivo. Un sitio fijo y aparte:
    # así sabes siempre dónde mirar y nada cae encima de tu trabajo.
    inbox_root: str = ""


def default_node_name() -> str:
    return socket.gethostname() or "dispositivo"


def default_inbox_root() -> Path:
    return Path.home() / "Vibi" / "Entrante"


def platform_label() -> str:
    return f"{platform.system()} {platform.release()}".strip() or "desconocida"


def default_projects_root() -> Path:
    return Path.home() / "proyectos"


def load(path: Path = CONFIG_PATH) -> NodeConfig | None:
    if path == CONFIG_PATH:
        path = compatible_path(path, LEGACY_CONFIG_PATH)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        return NodeConfig(
            url=data["url"],
            node_id=data["node_id"],
            token=data["token"],
            nombre=data["nombre"],
            projects_root=data["projects_root"],
            # Los nodos dados de alta antes de que existiera la carpeta de
            # entrada no la tienen escrita. Se quedan con la cadena vacía y es
            # la capacidad quien cae en la de por defecto: así lo que se lee es
            # exactamente lo que hay en el archivo, y no hace falta volver a
            # registrar la máquina.
            inbox_root=data.get("inbox_root") or "",
        )
    except KeyError as error:
        raise ValueError(
            f"{path} está incompleto (falta {error}); bórralo y vuelve a registrar"
        ) from error


def save(config: NodeConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Se crea vacío y con permisos restringidos ANTES de escribir el token:
    # así nunca existe un instante en que el secreto sea legible por otros.
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(asdict(config), handle, ensure_ascii=False, indent=2)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Windows no siempre respeta chmod; el archivo queda igualmente bajo
        # el perfil del usuario.
        pass


def websocket_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.startswith("https://"):
        return "wss://" + url[len("https://"):] + "/api/nodos/ws"
    if url.startswith("http://"):
        return "ws://" + url[len("http://"):] + "/api/nodos/ws"
    raise ValueError(f"URL de Vibi no soportada: {base_url}")

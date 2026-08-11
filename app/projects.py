"""Listado, clonado y eliminación segura de proyectos del usuario."""
import asyncio
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import db, tasks
from .config import settings

KNOWN_SSH_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
SSH_REPO = re.compile(
    r"^git@(?P<host>github\.com|gitlab\.com|bitbucket\.org):"
    r"(?P<path>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+?)(?:\.git)?$"
)


class ProjectError(ValueError):
    """Error de proyecto apto para traducirse a una respuesta de API."""


class InvalidRepoUrl(ProjectError):
    pass


class ProjectExists(ProjectError):
    pass


class CloneFailed(ProjectError):
    pass


class ProjectNotFound(ProjectError):
    pass


class ProjectInUse(ProjectError):
    pass


class DeleteFailed(ProjectError):
    pass


def _sanear_nombre(raw_name: str) -> str:
    name = re.sub(r"\.git$", "", unquote(raw_name), flags=re.IGNORECASE)
    if name in {"", ".", ".."}:
        raise InvalidRepoUrl("La URL no contiene un nombre de repositorio válido")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-_")
    if not safe or safe in {".", ".."}:
        raise InvalidRepoUrl("La URL no contiene un nombre de repositorio válido")
    return safe


def validar_url_repo(url: str) -> tuple[str, str]:
    """Valida una URL de Git y devuelve `(host, nombre_destino)` seguro."""
    if not url or url.startswith("-") or any(c.isspace() for c in url):
        raise InvalidRepoUrl("URL de repositorio no permitida")

    ssh = SSH_REPO.fullmatch(url)
    if ssh:
        parts = ssh.group("path").split("/")
        if any(part in {".", ".."} for part in parts):
            raise InvalidRepoUrl("La URL contiene una ruta no permitida")
        return ssh.group("host"), _sanear_nombre(parts[-1])

    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise InvalidRepoUrl("La URL contiene un puerto inválido") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or port
        or parsed.query
        or parsed.fragment
    ):
        raise InvalidRepoUrl(
            "Solo se admite HTTPS de GitHub o SSH de un host Git conocido"
        )
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 2 or any(part in {".", ".."} for part in parts):
        raise InvalidRepoUrl("La URL de GitHub debe identificar propietario y repo")
    return parsed.hostname, _sanear_nombre(parts[-1])


async def clonar_proyecto(user_id: str, url: str) -> str:
    """Clona sin shell y publica el repo solo cuando Git termina bien."""
    _, name = validar_url_repo(url)
    base = tasks.directorio_usuario(user_id)
    destination = (base / name).resolve()
    if destination.parent != base:
        raise InvalidRepoUrl("El destino queda fuera del workspace")
    if destination.exists():
        raise ProjectExists(f"Ya existe un proyecto llamado {name}")

    staging = (base / f".vibi-clone-{uuid.uuid4().hex}").resolve()
    if staging.parent != base:
        raise InvalidRepoUrl("El destino temporal queda fuera del workspace")

    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--",
            url,
            str(staging),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=settings.git_clone_timeout_seconds
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise CloneFailed(
                "git clone superó el tiempo máximo permitido"
            ) from error
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise CloneFailed(message or "git clone terminó con error")
        if not staging.is_dir():
            raise CloneFailed("git clone no creó el directorio esperado")
        if destination.exists():
            raise ProjectExists(f"Ya existe un proyecto llamado {name}")
        staging.replace(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    return name


def eliminar_proyecto(user_id: str, name: str) -> str:
    """Elimina un proyecto directo si no tiene tareas activas."""
    base = tasks.directorio_usuario(user_id)
    relative = Path(name)
    if (
        not name
        or relative.is_absolute()
        or len(relative.parts) != 1
        or name in {".", ".."}
    ):
        raise ProjectNotFound("Proyecto no encontrado")

    project = base / name
    try:
        if project.is_symlink() or not project.is_dir():
            raise ProjectNotFound("Proyecto no encontrado")
        resolved = project.resolve(strict=True)
    except OSError as error:
        raise ProjectNotFound("Proyecto no encontrado") from error
    if resolved.parent != base:
        raise ProjectNotFound("Proyecto no encontrado")

    for task in db.list_live_tasks(user_id):
        workspace = task.get("workspace")
        if workspace and Path(workspace).resolve() == resolved:
            raise ProjectInUse(
                "El proyecto tiene una tarea activa. Termínala o recházala antes de borrarlo"
            )

    try:
        shutil.rmtree(resolved)
    except OSError as error:
        raise DeleteFailed("No se pudo eliminar el directorio del proyecto") from error
    return name

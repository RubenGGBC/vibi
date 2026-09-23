"""Proyectos del usuario: carpeta de trabajo, archivos y conversaciones.

Un proyecto es dos cosas a la vez y las dos importan:

  - Una carpeta dentro del workspace del usuario, que es lo que un encargo
    agéntico recibe como directorio de trabajo. Eso ya existía.
  - Un registro en la base donde cuelgan los archivos que se le suben y las
    conversaciones que se guardan en él.

La carpeta manda sobre la existencia: un repo clonado a mano aparece como
proyecto aunque nadie lo registrara, y `sincronizar` le crea la ficha la
primera vez que se listan. Al revés no: borrar la carpeta no borra lo que
se guardó dentro, que sigue siendo del usuario.
"""
import asyncio
import re
import shutil
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import db, tasks
from .config import MANAGED_UPLOADS_DIRECTORY, settings

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


class InvalidProjectName(ProjectError):
    pass


def slug_de(nombre: str) -> str:
    """Convierte un nombre visible en el nombre de carpeta que le corresponde."""
    limpio = unicodedata.normalize("NFKD", (nombre or "").strip())
    ascii_only = "".join(c for c in limpio if not unicodedata.combining(c))
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_only).strip("-._")
    if not slug or slug in {".", ".."} or slug == MANAGED_UPLOADS_DIRECTORY:
        raise InvalidProjectName("Ponle un nombre con letras o números")
    return slug[:60]


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

    registrar(user_id, name)
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

    registro = db.get_project_by_slug(user_id, name)
    if registro:
        db.delete_project_record(registro["id"], user_id)
    return name


def _carpeta_proyecto(user_id: str, slug: str) -> Path:
    """La carpeta del proyecto, comprobando que no se sale del workspace."""
    base = tasks.directorio_usuario(user_id)
    destino = (base / slug).resolve()
    if destino.parent != base:
        raise InvalidProjectName("El proyecto queda fuera del workspace")
    return destino


def registrar(user_id: str, slug: str, nombre: str | None = None) -> dict:
    """Da de alta la ficha de un proyecto que ya tiene carpeta."""
    existente = db.get_project_by_slug(user_id, slug)
    if existente:
        return existente
    creado = db.create_project(user_id, nombre or slug, slug)
    # Una carrera con otra pestaña deja la ficha creada por el otro lado.
    return creado or db.get_project_by_slug(user_id, slug)


def crear_proyecto(user_id: str, nombre: str, descripcion: str = "") -> dict:
    """Crea un proyecto vacío: su carpeta de trabajo y su ficha."""
    slug = slug_de(nombre)
    destino = _carpeta_proyecto(user_id, slug)
    if destino.exists() or db.get_project_by_slug(user_id, slug):
        raise ProjectExists(f"Ya existe un proyecto llamado {slug}")
    try:
        destino.mkdir(parents=False, exist_ok=False)
    except FileExistsError as error:
        raise ProjectExists(f"Ya existe un proyecto llamado {slug}") from error
    except OSError as error:
        raise ProjectError("No se pudo crear la carpeta del proyecto") from error

    proyecto = db.create_project(user_id, nombre.strip() or slug, slug, descripcion)
    if not proyecto:
        # La ficha es lo que hace utilizable al proyecto; sin ella la carpeta
        # recién creada solo estorba.
        shutil.rmtree(destino, ignore_errors=True)
        raise ProjectExists(f"Ya existe un proyecto llamado {slug}")
    return proyecto


def sincronizar(user_id: str) -> list[dict]:
    """Lista los proyectos uniendo lo que hay en disco con lo que hay en la base.

    Cada carpeta del workspace es un proyecto aunque nadie la registrara —así
    entran los repos clonados antes de que existieran las fichas—, y cada ficha
    sigue apareciendo aunque su carpeta ya no esté, porque lo que se guardó
    dentro no desaparece con el directorio.
    """
    carpetas = tasks.listar_proyectos(user_id)
    fichas = {ficha["slug"]: ficha for ficha in db.list_projects(user_id)}
    for slug in carpetas:
        if slug not in fichas:
            registrar(user_id, slug)
    proyectos = db.list_projects(user_id)
    en_disco = set(carpetas)
    for proyecto in proyectos:
        proyecto["carpeta"] = proyecto["slug"] in en_disco
    return proyectos


def obtener(user_id: str, project_id: str) -> dict:
    proyecto = db.get_project(project_id, user_id)
    if not proyecto:
        raise ProjectNotFound("Proyecto no encontrado")
    proyecto["carpeta"] = _carpeta_proyecto(user_id, proyecto["slug"]).is_dir()
    return proyecto


def renombrar(
    user_id: str,
    project_id: str,
    nombre: str | None = None,
    descripcion: str | None = None,
) -> dict:
    """Cambia el nombre visible y la descripción; la carpeta no se mueve."""
    obtener(user_id, project_id)
    actualizado = db.update_project(project_id, user_id, nombre, descripcion)
    if not actualizado:
        raise ProjectNotFound("Proyecto no encontrado")
    return actualizado


def eliminar_por_id(user_id: str, project_id: str, borrar_carpeta: bool = True) -> dict:
    """Borra un proyecto por su identificador, con o sin su carpeta."""
    proyecto = obtener(user_id, project_id)
    if borrar_carpeta and proyecto["carpeta"]:
        eliminar_proyecto(user_id, proyecto["slug"])
    db.delete_project_record(project_id, user_id)
    return proyecto

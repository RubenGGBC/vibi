"""Archivos personales confinados al usuario autenticado."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from collections.abc import AsyncIterator
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import UploadFile

from . import db, tasks
from .config import MANAGED_UPLOADS_DIRECTORY, settings

log = logging.getLogger("vibi.files")


class FileServiceError(Exception):
    pass


class FileTooLarge(FileServiceError):
    pass


class FileQuotaExceeded(FileServiceError):
    pass


class UnsafeFilePath(FileServiceError):
    pass


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
_CLAUDE_CWD_FILE = re.compile(r"^tmpclaude-[0-9a-f]+-cwd$", re.IGNORECASE)
_CONTENT_EXTENSIONS = {".csv", ".docx", ".json", ".md", ".markdown", ".pdf", ".rtf", ".txt"}
_WORKSPACE_INDEX_TTL_SECONDS = 5.0
_workspace_indexed_at: dict[str, float] = {}
_workspace_index_locks: dict[str, threading.Lock] = {}
_workspace_index_locks_guard = threading.Lock()
_managed_file_locks: dict[str, threading.Lock] = {}
_managed_file_locks_guard = threading.Lock()
_SEARCH_STOP_WORDS = {
    "archivo", "archivos", "contenido", "documento", "documentos", "dentro",
    "como", "dime", "donde", "el", "ella", "en", "es", "ese", "esta", "este", "fichero",
    "la", "las", "lee", "leer", "leerme", "lo", "los", "me", "mi", "mio", "vibi",
    "llama", "pc", "por", "porfa", "puedes", "que", "quiero", "se", "subido", "tengo", "tienes",
    "un", "una", "y",
}


def _safe_name(raw_name: str | None) -> str:
    name = Path((raw_name or "archivo").replace("\\", "/")).name
    name = _CONTROL_CHARS.sub("", name).strip().strip(".")
    if not name:
        name = "archivo"
    return name[:255]


def _normalize_search_text(text: str) -> str:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def _search_terms(query: str) -> list[str]:
    terms: list[str] = []
    for term in _normalize_search_text(query).split():
        if term in _SEARCH_STOP_WORDS or (len(term) < 2 and not term.isdigit()):
            continue
        if term not in terms:
            terms.append(term)
    return terms


def _is_internal_workspace_file(path_or_name: str) -> bool:
    """Oculta archivos auxiliares de Claude Code que no pertenecen al usuario."""
    name = path_or_name.replace("\\", "/").rsplit("/", 1)[-1]
    return bool(_CLAUDE_CWD_FILE.fullmatch(name))


def _workspace_index_lock(user_id: str) -> threading.Lock:
    with _workspace_index_locks_guard:
        return _workspace_index_locks.setdefault(user_id, threading.Lock())


def _managed_file_lock(user_id: str) -> threading.Lock:
    with _managed_file_locks_guard:
        return _managed_file_locks.setdefault(user_id, threading.Lock())


def _ensure_workspace_index(user_id: str) -> int:
    """Evita recorrer todo el workspace varias veces dentro del mismo turno."""
    now = time.monotonic()
    if now - _workspace_indexed_at.get(user_id, 0.0) < _WORKSPACE_INDEX_TTL_SECONDS:
        return 0
    with _workspace_index_lock(user_id):
        now = time.monotonic()
        if (
            now - _workspace_indexed_at.get(user_id, 0.0)
            < _WORKSPACE_INDEX_TTL_SECONDS
        ):
            return 0
        try:
            return index_workspace(user_id)
        finally:
            _workspace_indexed_at[user_id] = time.monotonic()


def _extract_text(path: Path, name: str, max_chars: int) -> str:
    if path.stat().st_size > settings.file_content_max_bytes:
        return ""
    suffix = Path(name).suffix.casefold()
    if suffix not in _CONTENT_EXTENSIONS:
        return ""
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            parts: list[str] = []
            total = 0
            for page in PdfReader(path).pages:
                text = page.extract_text() or ""
                parts.append(text)
                total += len(text)
                if total >= max_chars:
                    break
            return "\n".join(parts)[:max_chars]
        if suffix == ".docx":
            from docx import Document

            document = Document(path)
            return "\n".join(
                paragraph.text for paragraph in document.paragraphs
            )[:max_chars]
        raw = path.read_bytes()[: max_chars * 4]
        if b"\x00" in raw[:2_000]:
            return ""
        return raw.decode("utf-8", errors="replace")[:max_chars]
    except Exception as error:
        log.info("No se pudo extraer texto de %s: %s", name, error)
        return ""


def _index_file_content(file: dict, user_id: str) -> str:
    if file.get("content_indexed_at") is not None:
        return file.get("content_text") or ""
    try:
        path = path_for_file(file, user_id)
        text = _extract_text(path, file["name"], settings.file_content_index_chars)
    except (OSError, UnsafeFilePath):
        text = ""
    normalized = _normalize_search_text(text)
    try:
        db.set_file_content_index(file["id"], user_id, normalized)
    except Exception as error:
        log.warning("No se pudo indexar %s: %s", file["name"], error)
    return normalized


def _managed_user_root(user_id: str) -> Path:
    workspace = Path(tasks.directorio_usuario(user_id))
    user_root = workspace / MANAGED_UPLOADS_DIRECTORY
    if user_root.is_symlink():
        raise UnsafeFilePath("Directorio de archivos inválido")
    user_root.mkdir(parents=True, exist_ok=True)
    resolved = user_root.resolve()
    if resolved.parent != workspace:
        raise UnsafeFilePath("Directorio de archivos inválido")
    return resolved


def _legacy_managed_user_root(user_id: str) -> Path:
    root = Path(settings.file_storage_root).expanduser().resolve()
    user_root = (root / user_id).resolve()
    if user_root.parent != root:
        raise UnsafeFilePath("Directorio histórico inválido")
    return user_root


def _managed_path(root: Path, storage_key: str) -> Path | None:
    relative = Path(str(storage_key))
    if (
        relative.is_absolute()
        or len(relative.parts) != 1
        or relative.name in {"", ".", ".."}
    ):
        return None
    candidate = root / relative.name
    if candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if resolved.parent != root or not resolved.is_file():
        return None
    return resolved


def _candidate_names(raw_name: str):
    name = _safe_name(raw_name)
    path = Path(name)
    suffix = path.suffix
    stem = name[: -len(suffix)] if suffix else name
    yield name
    counter = 2
    while True:
        addition = f" ({counter})"
        numbered_suffix = suffix[: max(0, 254 - len(addition))]
        available = max(1, 255 - len(addition) - len(numbered_suffix))
        yield f"{stem[:available]}{addition}{numbered_suffix}"
        counter += 1


def _available_managed_name(
    root: Path,
    raw_name: str,
    reserved: set[str],
) -> str:
    for candidate in _candidate_names(raw_name):
        path = root / candidate
        if candidate not in reserved and not path.exists() and not path.is_symlink():
            return candidate
    raise FileServiceError("No se pudo reservar un nombre para el archivo")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _matches_managed_record(path: Path, file: dict) -> bool:
    try:
        if path.stat().st_size != int(file["size_bytes"]):
            return False
        expected = str(file.get("sha256") or "")
        return not expected or _sha256_file(path) == expected
    except OSError:
        return False


def _workspace_path(user_id: str, relative_path: str) -> Path:
    root = tasks.directorio_usuario(user_id)
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise UnsafeFilePath("Ruta de archivo inválida")
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise UnsafeFilePath("No se permiten enlaces simbólicos")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise UnsafeFilePath("El archivo queda fuera del espacio del usuario") from error
    if not resolved.is_file():
        raise UnsafeFilePath("El recurso no es un archivo")
    return resolved


def path_for_file(file: dict, user_id: str) -> Path:
    if file["user_id"] != user_id:
        raise UnsafeFilePath("Archivo no disponible")
    if file["source"] == "managed":
        path = _managed_path(_managed_user_root(user_id), file["storage_key"])
        if path is not None:
            return path
        legacy = _managed_path(
            _legacy_managed_user_root(user_id), file["storage_key"]
        )
        if legacy is not None:
            return legacy
        raise UnsafeFilePath("Archivo no disponible")
    return _workspace_path(user_id, file["relative_path"])


def _workspace_directory(user_id: str, relative_path: str = "") -> Path:
    root = tasks.directorio_usuario(user_id)
    if not relative_path:
        return root
    relative = Path(relative_path.replace("\\", "/"))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise UnsafeFilePath("Ruta de carpeta inválida")
    current = root
    for part in relative.parts:
        if (
            part in _IGNORED_DIRS
            or part == MANAGED_UPLOADS_DIRECTORY
            or part.startswith(".vibi-")
        ):
            raise UnsafeFilePath("Carpeta no disponible")
        current = current / part
        if current.is_symlink():
            raise UnsafeFilePath("No se permiten enlaces simbólicos")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise UnsafeFilePath("Carpeta no disponible") from error
    if not resolved.is_dir():
        raise UnsafeFilePath("El recurso no es una carpeta")
    return resolved


async def store_stream(
    user_id: str,
    name: str | None,
    chunks: AsyncIterator[bytes],
    *,
    content_type: str | None = None,
    ignorar_limites: bool = False,
) -> dict:
    """Guarda un flujo de bytes como archivo gestionado del usuario.

    Es el único camino de escritura: la subida de la PWA y las transferencias
    entre dispositivos acaban las dos aquí, para que no se separen con el
    tiempo.

    Con `ignorar_limites` no se aplican `file_max_bytes` ni la cuota. Ese flag
    solo lo activa una transferencia cuyo tamaño el usuario ya ha visto y
    confirmado: el límite deja de ser un muro y pasa a ser el aviso que se le
    dio antes de mover nada.
    """
    safe_name = _safe_name(name)
    root = _managed_user_root(user_id)
    temporary = root / f".{uuid.uuid4()}.upload"
    digest = hashlib.sha256()
    total = 0
    try:
        with temporary.open("xb") as output:
            async for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                if not ignorar_limites:
                    if total > settings.file_max_bytes:
                        raise FileTooLarge("El archivo supera el tamaño máximo")
                    if (
                        db.managed_usage(user_id) + total
                        > settings.file_user_quota_bytes
                    ):
                        raise FileQuotaExceeded(
                            "Has alcanzado tu cuota de almacenamiento"
                        )
                digest.update(chunk)
                output.write(chunk)
        if total == 0:
            raise FileServiceError("El archivo está vacío")
        with _managed_file_lock(user_id):
            reserved = {
                file["storage_key"] for file in db.list_managed_files(user_id)
            }
            storage_key = _available_managed_name(root, safe_name, reserved)
            destination = root / storage_key
            os.replace(temporary, destination)
            stored: dict | None = None
            try:
                media_type = content_type or mimetypes.guess_type(storage_key)[0]
                if ignorar_limites:
                    stored = db.create_managed_file(
                        user_id,
                        storage_key,
                        storage_key,
                        media_type,
                        total,
                        digest.hexdigest(),
                    )
                else:
                    stored = db.create_managed_file_within_quota(
                        user_id,
                        storage_key,
                        storage_key,
                        media_type,
                        total,
                        digest.hexdigest(),
                        settings.file_user_quota_bytes,
                    )
                if not stored:
                    raise FileQuotaExceeded(
                        "Has alcanzado tu cuota de almacenamiento"
                    )
            except Exception:
                destination.unlink(missing_ok=True)
                if stored:
                    db.delete_managed_file_record(stored["id"], user_id)
                raise
        await asyncio.to_thread(_index_file_content, stored, user_id)
        return stored
    finally:
        temporary.unlink(missing_ok=True)


async def store_upload(user_id: str, upload: UploadFile) -> dict:
    async def _leer() -> AsyncIterator[bytes]:
        while chunk := await upload.read(1024 * 1024):
            yield chunk

    try:
        return await store_stream(
            user_id,
            upload.filename,
            _leer(),
            content_type=upload.content_type,
        )
    finally:
        await upload.close()


def create_text_file(user_id: str, name: str, content: str) -> dict:
    """Crea una nota UTF-8 gestionada con los mismos límites que una subida."""
    safe_name = _safe_name(name)
    raw = content.encode("utf-8")
    total = len(raw)
    if total == 0:
        raise FileServiceError("La nota está vacía")
    if total > settings.file_max_bytes:
        raise FileTooLarge("El archivo supera el tamaño máximo")
    if db.managed_usage(user_id) + total > settings.file_user_quota_bytes:
        raise FileQuotaExceeded("Has alcanzado tu cuota de almacenamiento")

    root = _managed_user_root(user_id)
    temporary = root / f".{uuid.uuid4()}.note"
    try:
        with temporary.open("xb") as output:
            output.write(raw)
        with _managed_file_lock(user_id):
            reserved = {
                file["storage_key"] for file in db.list_managed_files(user_id)
            }
            storage_key = _available_managed_name(root, safe_name, reserved)
            destination = root / storage_key
            os.replace(temporary, destination)
            stored: dict | None = None
            try:
                stored = db.create_managed_file_within_quota(
                    user_id,
                    storage_key,
                    storage_key,
                    "text/plain; charset=utf-8",
                    total,
                    hashlib.sha256(raw).hexdigest(),
                    settings.file_user_quota_bytes,
                )
                if not stored:
                    raise FileQuotaExceeded(
                        "Has alcanzado tu cuota de almacenamiento"
                    )
            except Exception:
                destination.unlink(missing_ok=True)
                if stored:
                    db.delete_managed_file_record(stored["id"], user_id)
                raise
        _index_file_content(stored, user_id)
        return stored
    finally:
        temporary.unlink(missing_ok=True)


def _migration_destination(
    root: Path,
    file: dict,
    reserved: set[str],
) -> tuple[str, Path | None]:
    for candidate in _candidate_names(file["name"]):
        if candidate in reserved:
            continue
        existing = _managed_path(root, candidate)
        if existing is not None:
            if _matches_managed_record(existing, file):
                return candidate, existing
            continue
        path = root / candidate
        if not path.exists() and not path.is_symlink():
            return candidate, None
    raise FileServiceError("No se pudo reservar un nombre para la migración")


def ensure_managed_uploads_visible(user_id: str) -> int:
    """Migra blobs históricos al directorio que ven los motores de Vibi."""
    root = _managed_user_root(user_id)
    legacy_root = _legacy_managed_user_root(user_id)
    migrated = 0

    with _managed_file_lock(user_id):
        records = db.list_managed_files(user_id)
        reserved = {
            file["storage_key"]
            for file in records
            if _managed_path(root, file["storage_key"]) is not None
        }
        for file in records:
            if _managed_path(root, file["storage_key"]) is not None:
                continue
            legacy = _managed_path(legacy_root, file["storage_key"])
            if legacy is None:
                log.warning("No se encontró el blob gestionado %s", file["id"])
                continue

            try:
                storage_key, existing = _migration_destination(
                    root, file, reserved
                )
            except FileServiceError as error:
                log.warning("No se pudo migrar %s: %s", file["name"], error)
                continue

            destination = root / storage_key
            created = False
            temporary = root / f".{file['id']}.migrate"
            try:
                if existing is None:
                    temporary.unlink(missing_ok=True)
                    shutil.copyfile(legacy, temporary)
                    if not _matches_managed_record(temporary, file):
                        raise FileServiceError(
                            "la copia no coincide en tamaño o SHA-256"
                        )
                    os.replace(temporary, destination)
                    created = True

                updated = db.update_managed_file_location(
                    file["id"], user_id, storage_key, storage_key
                )
                if updated is None:
                    raise FileServiceError(
                        "la fila dejó de estar disponible durante la migración"
                    )
            except Exception as error:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                if created:
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        pass
                log.warning("No se pudo migrar %s: %s", file["name"], error)
                continue

            reserved.add(storage_key)
            migrated += 1
            try:
                legacy.unlink()
            except OSError as error:
                log.warning(
                    "La copia de %s ya está activa, pero no se pudo retirar "
                    "el blob histórico: %s",
                    storage_key,
                    error,
                )

    return migrated


def index_workspace(user_id: str) -> int:
    root = tasks.directorio_usuario(user_id)
    indexed = 0
    for current_root, dirs, names in os.walk(root, followlinks=False):
        current = Path(current_root)
        dirs[:] = [
            name
            for name in dirs
            if name not in _IGNORED_DIRS
            and name != MANAGED_UPLOADS_DIRECTORY
            and not name.startswith(".vibi-")
            and not (current / name).is_symlink()
        ]
        for name in names:
            if indexed >= settings.file_scan_limit:
                return indexed
            if _is_internal_workspace_file(name):
                continue
            path = current / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                stat = path.stat()
                file = db.upsert_workspace_file(
                    user_id,
                    relative,
                    name,
                    stat.st_size,
                    stat.st_mtime,
                    mimetypes.guess_type(name)[0],
                )
                _index_file_content(file, user_id)
                indexed += 1
            except (OSError, ValueError):
                continue
    return indexed


def search_files(user_id: str, query: str = "", limit: int | None = None) -> list[dict]:
    _ensure_workspace_index(user_id)
    requested_limit = min(limit or settings.file_search_limit, settings.file_search_limit)
    terms = _search_terms(query)
    ranked: list[tuple[float, dict]] = []
    for file in db.list_files(user_id, max(settings.file_scan_limit, requested_limit)):
        if file["source"] == "workspace" and _is_internal_workspace_file(
            file.get("relative_path") or file["name"]
        ):
            continue
        content = _index_file_content(file, user_id)
        if not terms:
            ranked.append((0, file))
            continue
        metadata = _normalize_search_text(
            " ".join(
                value
                for value in (file["name"], file.get("relative_path") or "")
                if value
            )
        )
        metadata_words = metadata.split()
        score = 0.0
        matched = 0
        for term in terms:
            in_metadata = term in metadata
            in_content = term in content
            fuzzy = any(
                SequenceMatcher(None, term, word).ratio() >= 0.78
                for word in metadata_words
            )
            if in_metadata or in_content or fuzzy:
                matched += 1
                score += 12 if in_metadata else 7 if fuzzy else 2
        if not matched:
            continue
        coverage = matched / len(terms)
        score += coverage * 10
        if matched == len(terms):
            score += 12
        ranked.append((score, file))
    ranked.sort(key=lambda item: item[0], reverse=True)
    found: list[dict] = []
    for _, file in ranked:
        try:
            path_for_file(file, user_id)
        except UnsafeFilePath:
            continue
        found.append(file)
        if len(found) >= requested_limit:
            break
    return found


def read_file(user_id: str, query: str) -> tuple[dict | None, str]:
    found = search_files(user_id, query, 10)
    for file in found:
        try:
            text = _extract_text(
                path_for_file(file, user_id),
                file["name"],
                settings.file_content_read_chars,
            ).strip()
        except (OSError, UnsafeFilePath):
            continue
        if text:
            return file, text
    return (found[0], "") if found else (None, "")


def list_directory(
    user_id: str, relative_path: str = "", limit: int | None = None
) -> tuple[list[dict], list[dict]]:
    """Lista un nivel del workspace sin exponer rutas absolutas."""
    root = tasks.directorio_usuario(user_id)
    directory = _workspace_directory(user_id, relative_path)
    requested_limit = min(limit or settings.file_search_limit, settings.file_search_limit)
    folders: list[dict] = []
    workspace_files: list[dict] = []

    try:
        entries = sorted(directory.iterdir(), key=lambda entry: entry.name.casefold())
    except OSError as error:
        raise FileServiceError("No se pudo leer la carpeta") from error

    for entry in entries:
        try:
            if (
                entry.name == MANAGED_UPLOADS_DIRECTORY
                or _is_internal_workspace_file(entry.name)
            ):
                continue
            if entry.is_symlink():
                continue
            entry_relative = entry.relative_to(root).as_posix()
            if entry.is_dir():
                if entry.name in _IGNORED_DIRS or entry.name.startswith(".vibi-"):
                    continue
                folders.append({"name": entry.name, "path": entry_relative})
            elif entry.is_file() and len(workspace_files) < requested_limit:
                stat = entry.stat()
                workspace_files.append(
                    db.upsert_workspace_file(
                        user_id,
                        entry_relative,
                        entry.name,
                        stat.st_size,
                        stat.st_mtime,
                        mimetypes.guess_type(entry.name)[0],
                    )
                )
        except (OSError, ValueError):
            continue

    if relative_path:
        return folders, workspace_files

    managed_files = [
        file
        for file in db.list_files(
            user_id, max(settings.file_scan_limit, requested_limit)
        )
        if file["source"] == "managed"
    ][:requested_limit]
    available = max(0, requested_limit - len(managed_files))
    return folders, managed_files + workspace_files[:available]


def delete_managed_file(user_id: str, file_id: str) -> bool:
    file = db.get_file_for_user(file_id, user_id)
    if not file or file["source"] != "managed":
        return False
    deleted = db.soft_delete_file(file_id, user_id)
    if not deleted:
        return False
    try:
        path_for_file(file, user_id).unlink(missing_ok=True)
    except UnsafeFilePath:
        pass
    return True

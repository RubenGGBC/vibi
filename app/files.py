"""Archivos personales confinados al usuario autenticado."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import re
import threading
import time
import unicodedata
import uuid
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import UploadFile

from . import db, tasks
from .config import settings

log = logging.getLogger("morgana.files")


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
_SEARCH_STOP_WORDS = {
    "archivo", "archivos", "contenido", "documento", "documentos", "dentro",
    "como", "dime", "donde", "el", "ella", "en", "es", "ese", "esta", "este", "fichero",
    "la", "las", "lee", "leer", "leerme", "lo", "los", "me", "mi", "mio", "morgana",
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


def invalidate_workspace_index(user_id: str) -> None:
    """Fuerza un escaneo nuevo en la próxima búsqueda del usuario."""
    with _workspace_index_lock(user_id):
        _workspace_indexed_at.pop(user_id, None)


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
    root = Path(settings.file_storage_root).expanduser().resolve()
    user_root = (root / user_id).resolve()
    if user_root.parent != root:
        raise UnsafeFilePath("Directorio de archivos inválido")
    user_root.mkdir(parents=True, exist_ok=True)
    return user_root


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
        root = _managed_user_root(user_id)
        path = (root / file["storage_key"]).resolve()
        if path.parent != root or not path.is_file() or path.is_symlink():
            raise UnsafeFilePath("Archivo no disponible")
        return path
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
        if part in _IGNORED_DIRS or part.startswith(".morgana-"):
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


async def store_upload(user_id: str, upload: UploadFile) -> dict:
    name = _safe_name(upload.filename)
    root = _managed_user_root(user_id)
    storage_key = str(uuid.uuid4())
    temporary = root / f".{storage_key}.upload"
    destination = root / storage_key
    digest = hashlib.sha256()
    total = 0
    try:
        with temporary.open("xb") as output:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > settings.file_max_bytes:
                    raise FileTooLarge("El archivo supera el tamaño máximo")
                if db.managed_usage(user_id) + total > settings.file_user_quota_bytes:
                    raise FileQuotaExceeded("Has alcanzado tu cuota de almacenamiento")
                digest.update(chunk)
                output.write(chunk)
        if total == 0:
            raise FileServiceError("El archivo está vacío")
        os.replace(temporary, destination)
        stored: dict | None = None
        try:
            stored = db.create_managed_file_within_quota(
                user_id,
                name,
                storage_key,
                upload.content_type or mimetypes.guess_type(name)[0],
                total,
                digest.hexdigest(),
                settings.file_user_quota_bytes,
            )
            if not stored:
                raise FileQuotaExceeded("Has alcanzado tu cuota de almacenamiento")
            await asyncio.to_thread(_index_file_content, stored, user_id)
            return stored
        except Exception:
            destination.unlink(missing_ok=True)
            if stored:
                db.delete_managed_file_record(stored["id"], user_id)
            raise
    finally:
        temporary.unlink(missing_ok=True)
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
    storage_key = str(uuid.uuid4())
    temporary = root / f".{storage_key}.note"
    destination = root / storage_key
    try:
        with temporary.open("xb") as output:
            output.write(raw)
        os.replace(temporary, destination)
        stored: dict | None = None
        try:
            stored = db.create_managed_file_within_quota(
                user_id,
                safe_name,
                storage_key,
                "text/plain; charset=utf-8",
                total,
                hashlib.sha256(raw).hexdigest(),
                settings.file_user_quota_bytes,
            )
            if not stored:
                raise FileQuotaExceeded("Has alcanzado tu cuota de almacenamiento")
            _index_file_content(stored, user_id)
            return stored
        except Exception:
            destination.unlink(missing_ok=True)
            if stored:
                db.delete_managed_file_record(stored["id"], user_id)
            raise
    finally:
        temporary.unlink(missing_ok=True)


def index_workspace(user_id: str) -> int:
    root = tasks.directorio_usuario(user_id)
    indexed = 0
    for current_root, dirs, names in os.walk(root, followlinks=False):
        current = Path(current_root)
        dirs[:] = [
            name
            for name in dirs
            if name not in _IGNORED_DIRS
            and not name.startswith(".morgana-")
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
            if _is_internal_workspace_file(entry.name):
                continue
            if entry.is_symlink():
                continue
            entry_relative = entry.relative_to(root).as_posix()
            if entry.is_dir():
                if entry.name in _IGNORED_DIRS or entry.name.startswith(".morgana-"):
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

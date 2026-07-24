"""Archivos personales confinados al usuario autenticado."""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from . import db, tasks
from .config import settings


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


def _safe_name(raw_name: str | None) -> str:
    name = Path((raw_name or "archivo").replace("\\", "/")).name
    name = _CONTROL_CHARS.sub("", name).strip().strip(".")
    if not name:
        name = "archivo"
    return name[:255]


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
        try:
            return db.create_managed_file(
                user_id,
                name,
                storage_key,
                upload.content_type or mimetypes.guess_type(name)[0],
                total,
                digest.hexdigest(),
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    finally:
        temporary.unlink(missing_ok=True)
        await upload.close()


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
            path = current / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                stat = path.stat()
                db.upsert_workspace_file(
                    user_id,
                    relative,
                    name,
                    stat.st_size,
                    stat.st_mtime,
                    mimetypes.guess_type(name)[0],
                )
                indexed += 1
            except (OSError, ValueError):
                continue
    return indexed


def search_files(user_id: str, query: str = "", limit: int | None = None) -> list[dict]:
    index_workspace(user_id)
    requested_limit = min(limit or settings.file_search_limit, settings.file_search_limit)
    terms = [term for term in query.casefold().split() if term]
    matches: list[dict] = []
    for file in db.list_files(user_id, max(settings.file_scan_limit, requested_limit)):
        haystack = " ".join(
            value for value in (file["name"], file.get("relative_path") or "") if value
        ).casefold()
        if terms and not all(term in haystack for term in terms):
            continue
        try:
            path_for_file(file, user_id)
        except UnsafeFilePath:
            continue
        matches.append(file)
        if len(matches) >= requested_limit:
            break
    return matches


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

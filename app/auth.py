"""Autenticación compartida por la API HTTP y el WebSocket."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from . import db
from .config import settings

ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("La contraseña no puede estar vacía")
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("La contraseña no puede superar 72 bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("ascii")
        )
    except (TypeError, ValueError):
        return False


def _jwt_secret() -> str:
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET no está configurado")
    return settings.jwt_secret


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_expiration_days),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])
    if not payload.get("sub"):
        raise InvalidTokenError("Token sin sujeto")
    return payload


def user_from_token(token: str) -> dict | None:
    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        return None
    return db.get_user_by_id(payload["sub"])


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = user_from_token(credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o caducado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def current_voice_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    """Acepta JWT normal o token revocable de nodo solo en voz y TTS."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = user_from_token(credentials.credentials)
    if user:
        return user

    # Importación local: nodes importa db/config y no debe crear un ciclo.
    from . import nodes

    node = nodes.node_from_token(credentials.credentials)
    if node:
        user = db.get_user_by_id(node["user_id"])
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido, caducado o revocado",
        headers={"WWW-Authenticate": "Bearer"},
    )

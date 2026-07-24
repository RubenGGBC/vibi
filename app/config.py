"""Configuración central de Morgana.

Todo sale de variables de entorno (.env). Nada hardcodeado,
para que migrar de máquina sea copiar el .env y listo.
"""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Identidad ---
    app_name: str = "Morgana"

    # --- Vía rápida (Groq) ---
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"  # modelo rápido por defecto
    groq_web_search_enabled: bool = True
    groq_search_model: str = "groq/compound-mini"
    groq_task_context_tokens: int = 200
    groq_recent_context_tokens: int = 4_000
    groq_speech_model: str = "whisper-large-v3-turbo"
    voice_max_audio_bytes: int = 5_000_000

    # --- Vía agéntica (Claude Agent SDK) ---
    # auto: usa API key si existe; si no, el login persistido de Claude Code.
    # api: exige ANTHROPIC_API_KEY. subscription: ignora la key y usa Claude Pro/Max.
    claude_auth_mode: Literal["auto", "api", "subscription"] = "auto"
    anthropic_api_key: str = ""

    # --- Telegram ---
    telegram_bot_token: str = ""
    # chat_id autorizado en fase 1 (un solo usuario). 0 = aceptar el primero que haga /start
    telegram_owner_chat_id: int = 0

    # --- PWA / API ---
    jwt_secret: str = ""
    jwt_expiration_days: int = 30
    pwa_base_url: str = "http://localhost:8000"
    frontend_dist: str = "./frontend/dist"
    git_clone_timeout_seconds: int = 300

    # --- Workspaces ---
    # Directorio raíz donde viven los proyectos sobre los que trabaja el agente.
    # En fase 2 esto será /home/<usuario>/workspace por cada user de Linux.
    workspace_root: str = "./workspace"

    # --- Archivos personales ---
    # Los blobs subidos se guardan fuera de los repositorios. Los archivos que
    # ya existen en WORKSPACE_ROOT/<user_id> también se pueden buscar y bajar.
    file_storage_root: str = "./data/files"
    file_max_bytes: int = 100_000_000
    file_user_quota_bytes: int = 2_000_000_000
    file_scan_limit: int = 10_000
    file_search_limit: int = 100

    # --- Base de datos ---
    db_path: str = "./data/morgana.db"


settings = Settings()

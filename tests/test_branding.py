from pathlib import Path

from app import api, config


def test_default_identity_is_vibi(monkeypatch):
    """Evita que el backend vuelva a presentarse con la marca anterior."""
    monkeypatch.delenv("APP_NAME", raising=False)

    assert config.Settings(_env_file=None).app_name == "Vibi"


def test_lone_legacy_database_is_adopted_without_losing_bytes(tmp_path: Path):
    """Una actualización no puede arrancar con una base vacía nueva."""
    legacy = tmp_path / "morgana.db"
    current = tmp_path / "vibi.db"
    payload = b"datos sqlite existentes"
    legacy.write_bytes(payload)

    resolved = config.resolve_vibi_db_path(current, legacy)

    assert resolved == current
    assert current.read_bytes() == payload
    assert not legacy.exists()


def test_vibi_closes_an_active_voice_invocation():
    """Las frases de despedida deben reconocer el nombre nuevo."""
    normalized = api._normalizar_orden_voz("Gracias, Vibi!")

    assert normalized in api.ORDENES_CERRAR_CONVERSACION

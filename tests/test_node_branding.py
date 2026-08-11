from pathlib import Path

from agent.vibi_node import config


def test_current_vibi_environment_value_has_priority(monkeypatch):
    """Una variable nueva nunca debe quedar tapada por su alias antiguo."""
    monkeypatch.setenv("VIBI_EXAMPLE", "nuevo")
    monkeypatch.setenv("MORGANA_EXAMPLE", "anterior")

    assert config.environment_value("VIBI_EXAMPLE", "MORGANA_EXAMPLE") == "nuevo"


def test_legacy_environment_value_remains_readable(monkeypatch):
    """Actualizar el agente no obliga a reescribir el entorno el mismo día."""
    monkeypatch.delenv("VIBI_EXAMPLE", raising=False)
    monkeypatch.setenv("MORGANA_EXAMPLE", "anterior")

    assert config.environment_value("VIBI_EXAMPLE", "MORGANA_EXAMPLE") == "anterior"


def test_legacy_path_is_reused_when_vibi_path_does_not_exist(tmp_path: Path):
    legacy = tmp_path / "morgana" / "node.json"
    legacy.parent.mkdir()
    legacy.write_text("configuración anterior", encoding="utf-8")

    assert config.compatible_path(tmp_path / "vibi" / "node.json", legacy) == legacy


def test_vibi_path_wins_when_both_paths_exist(tmp_path: Path):
    current = tmp_path / "vibi" / "node.json"
    legacy = tmp_path / "morgana" / "node.json"
    current.parent.mkdir()
    legacy.parent.mkdir()
    current.write_text("configuración nueva", encoding="utf-8")
    legacy.write_text("configuración anterior", encoding="utf-8")

    assert config.compatible_path(current, legacy) == current

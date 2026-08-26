"""El retrato del equipo contado sin revelar contenido.

Aquí se prueban los cálculos del mapa agregado: qué carpetas hay, cuántos
archivos de cada tipo, y cuándo fueron tocadas. Ni un nombre de archivo ni
una línea de contenido salen del equipo en este nivel.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import inventario  # noqa: E402


def test_cuenta_extensiones_sin_revelar_nombres(tmp_path):
    carpeta = tmp_path / "Farmacologia II"
    carpeta.mkdir()
    (carpeta / "tema-1-secreto.pdf").write_text("x")
    (carpeta / "tema-2-secreto.pdf").write_text("x")
    (carpeta / "notas.docx").write_text("x")

    mapa = inventario.mapa_de([tmp_path])
    entrada = [c for c in mapa["carpetas"] if c["ruta"].endswith("Farmacologia II")][0]
    assert entrada["extensiones"] == {"pdf": 2, "docx": 1}
    serializado = str(mapa)
    assert "secreto" not in serializado


def test_una_carpeta_vacia_no_aparece(tmp_path):
    (tmp_path / "vacia").mkdir()
    mapa = inventario.mapa_de([tmp_path])
    assert all(not c["ruta"].endswith("vacia") for c in mapa["carpetas"])


def test_respeta_el_tope_de_carpetas(tmp_path):
    for i in range(40):
        carpeta = tmp_path / f"c{i}"
        carpeta.mkdir()
        (carpeta / "a.pdf").write_text("x")
    mapa = inventario.mapa_de([tmp_path], tope_carpetas=25)
    assert len(mapa["carpetas"]) == 25


def test_una_raiz_que_no_existe_no_revienta(tmp_path):
    mapa = inventario.mapa_de([tmp_path / "no-existe"])
    assert mapa["carpetas"] == []

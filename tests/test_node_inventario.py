"""El retrato del equipo contado sin revelar contenido.

Aquí se prueban los cálculos del mapa agregado: qué carpetas hay, cuántos
archivos de cada tipo, y cuándo fueron tocadas. Ni un nombre de archivo ni
una línea de contenido salen del equipo en este nivel.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

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


def test_la_salida_trae_la_clave_apps(tmp_path):
    """La salida siempre incluye la clave 'apps', con o sin aplicaciones."""
    (tmp_path / "documentos").mkdir()
    (tmp_path / "documentos" / "a.pdf").write_text("x")
    mapa = inventario.mapa_de([tmp_path])
    assert "apps" in mapa
    assert isinstance(mapa["apps"], list)


def test_apps_lista_vacia_cuando_falla_descubrimiento(tmp_path):
    """Si discover_windows_apps() falla, 'apps' es lista vacía y no se interrumpe."""
    (tmp_path / "documentos").mkdir()
    (tmp_path / "documentos" / "a.pdf").write_text("x")
    with patch("vibi_node.inventario.app_catalog.discover_windows_apps") as mock:
        mock.side_effect = RuntimeError("Simulado: fallo al descubrir apps")
        mapa = inventario.mapa_de([tmp_path])
        assert mapa["apps"] == []
        assert len(mapa["carpetas"]) > 0  # El mapa se devuelve igual


def test_sufijo_largo_no_se_cuenta(tmp_path):
    """Sufijos > 8 caracteres no se cuentan, evita filtrar texto libre."""
    carpeta = tmp_path / "documentos"
    carpeta.mkdir()
    # Un archivo con sufijo largo (> 8 chars)
    (carpeta / "archivo.borrador-secreto-confidencial").write_text("x")
    # Un archivo con sufijo válido
    (carpeta / "readme.txt").write_text("x")
    mapa = inventario.mapa_de([tmp_path])
    entrada = [c for c in mapa["carpetas"] if c["ruta"].endswith("documentos")][0]
    assert "borrador-secreto-confidencial" not in entrada["extensiones"]
    assert "txt" in entrada["extensiones"]


def test_sufijo_no_alfanumerico_no_se_cuenta(tmp_path):
    """Sufijos con caracteres no alfanuméricos no se cuentan."""
    carpeta = tmp_path / "documentos"
    carpeta.mkdir()
    # Un archivo con sufijo que tiene guiones y espacios
    (carpeta / "archivo.mi-tipo-raro").write_text("x")
    # Un archivo con sufijo válido
    (carpeta / "readme.pdf").write_text("x")
    mapa = inventario.mapa_de([tmp_path])
    entrada = [c for c in mapa["carpetas"] if c["ruta"].endswith("documentos")][0]
    assert "mi-tipo-raro" not in entrada["extensiones"]
    assert "pdf" in entrada["extensiones"]


def test_ruta_es_relativa_y_no_expone_cuenta(tmp_path):
    """La ruta es relativa a la raíz explorada, no contiene C:\\Users\\usuario."""
    # Profundidad es 2, así que esta estructura se descubre completamente
    carpeta_profunda = tmp_path / "Documentos" / "Proyecto"
    carpeta_profunda.mkdir(parents=True)
    (carpeta_profunda / "archivo.xlsx").write_text("x")
    mapa = inventario.mapa_de([tmp_path])
    entrada = [c for c in mapa["carpetas"] if "Proyecto" in c["ruta"]][0]
    ruta = entrada["ruta"]
    # No debe contener C:\ ni Users ni la raíz absoluta
    assert not ruta.startswith("C:")
    assert "Users" not in ruta
    assert str(tmp_path) not in ruta
    # Debe contener la jerarquía relativa
    assert "Documentos" in ruta
    assert "Proyecto" in ruta

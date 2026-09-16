"""Vigilancias de resultados que aparecen en el disco."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import vigilancias as vigilancias_nodo  # noqa: E402

from app import tools  # noqa: E402


def test_sonda_archivo_distingue_ausencia_y_presencia(tmp_path: Path):
    destino = tmp_path / "descarga.zip"

    ausente = vigilancias_nodo._sondear_archivo({"ruta": str(destino)})
    destino.write_bytes(b"contenido")
    presente = vigilancias_nodo._sondear_archivo({"ruta": str(destino)})

    assert ausente[0] == "ausente"
    assert presente[0] == "presente"
    assert "9 bytes" in presente[1]


def test_sonda_archivo_ignora_que_una_descarga_crezca(tmp_path: Path):
    destino = tmp_path / "descarga.zip.part"
    destino.write_bytes(b"mitad")
    primer_sello, _ = vigilancias_nodo._sondear_archivo({"ruta": str(destino)})
    destino.write_bytes(b"contenido completo")
    segundo_sello, _ = vigilancias_nodo._sondear_archivo({"ruta": str(destino)})

    assert primer_sello == segundo_sello == "presente"


def test_parametros_exigen_ruta_final_y_admiten_continuacion():
    argumentos = tools.VigilarArguments(
        sonda="archivo",
        ruta=r"C:\Users\rebel\Downloads\juego.zip",
        que_espero="que termine la descarga",
        al_terminar="instala el juego",
    )

    assert tools._parametros_de_sonda(argumentos) == {
        "ruta": r"C:\Users\rebel\Downloads\juego.zip"
    }

    with pytest.raises(tools.InvalidToolArguments, match="ruta.*absoluta"):
        tools._parametros_de_sonda(
            tools.VigilarArguments(
                sonda="archivo", que_espero="que termine la descarga"
            )
        )

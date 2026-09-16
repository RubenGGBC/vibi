import asyncio
import sys
from datetime import datetime, time as hora, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node.equipo_observador import (  # noqa: E402
    Seguimiento,
    Seguimientos,
    _segundos_de_trabajo,
    observar,
)
from vibi_node.equipo_senales import construir  # noqa: E402


def test_avance_de_directorio_no_publica_la_ruta(tmp_path: Path):
    seguimiento = Seguimiento(
        "seg-1", "avance", "archivo", {"ruta": str(tmp_path)}, 2.0
    )
    assert asyncio.run(observar(seguimiento, 1.0)) == (False, {})
    (tmp_path / "secreto-cliente.txt").write_text("contenido", encoding="utf-8")
    emitir, payload = asyncio.run(observar(seguimiento, 2.0))
    mensaje = construir("seg-1", "avance", 1, payload, observada_en=3.0)
    assert emitir is True
    assert "secreto-cliente" not in str(mensaje)
    assert "contenido" not in str(mensaje)


def test_entregado_solo_emite_en_la_transicion(tmp_path: Path):
    destino = tmp_path / "entrega.pdf"
    seguimiento = Seguimiento(
        "seg-2", "entregado", "archivo", {"ruta": str(destino)}, 2.0
    )
    assert asyncio.run(observar(seguimiento, 1.0))[0] is False
    destino.write_bytes(b"pdf")
    assert asyncio.run(observar(seguimiento, 2.0))[0] is True
    assert asyncio.run(observar(seguimiento, 3.0))[0] is False


def test_senal_sin_ack_se_reintenta_y_con_ack_se_descarta():
    seguimientos = Seguimientos()
    mensaje = construir("seg-3", "avance", 1, {}, observada_en=3.0)

    seguimientos.encolar(mensaje, 10.0)
    assert seguimientos.por_enviar(14.9) == []
    assert seguimientos.por_enviar(15.0) == [mensaje]
    assert seguimientos.por_enviar(19.9) == []

    seguimientos.confirmar(mensaje["id"])
    assert seguimientos.por_enviar(25.0) == []


def test_sin_avance_no_cuenta_la_noche_local():
    hoy = datetime.now().astimezone().date()
    desde = datetime.combine(hoy, hora(hour=23)).astimezone()
    hasta = datetime.combine(hoy + timedelta(days=1), hora(hour=9)).astimezone()
    assert _segundos_de_trabajo(desde.timestamp(), hasta.timestamp()) == 2 * 3600

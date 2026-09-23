"""Que un lector abierto no tumbe una escritura de latido.

El 30/08/2026 el `core.log` llevaba 222 «database is locked», 31 solo ese día.
No caían en sitios raros: `upsert_device` (128), `touch_device` (55) y
`touch_node` (28), es decir, los latidos del companion y del nodo PC. Y cada
uno de esos fallos mataba el WebSocket que lo pedía, así que el nodo se
desconectaba en mitad de un turno y `agy` se quedaba esperando una herramienta
que ya no iba a contestar:

    17:42:18  WebSocket de nodo interrumpido  <- database is locked en touch_node
    17:42:19  El nodo PC no pudo abrir el navegador: PC se desconectó
              antes de recibir la orden.

La causa es que la base estaba en `journal_mode=delete`, donde un lector
bloquea al escritor durante toda su transacción. Medido con seis lectores y
cuatro escritores sobre la base real (18 MB): la mediana de un latido pasaba de
12 ms en WAL a 1.335 ms en `delete`, con máximos de 3,9 s contra un
`busy_timeout` de 5 s.

Este test no mide tiempos —serían frágiles—, sino la propiedad que los explica:
en WAL un lector con la transacción abierta no impide escribir.
"""
import sqlite3

import pytest

from app import db


def test_la_base_esta_en_wal() -> None:
    with db._conn() as c:
        modo = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert modo.lower() == "wal"


def test_un_lector_abierto_no_bloquea_el_latido() -> None:
    """Con `delete` esto levantaba «database is locked»; con WAL, no."""
    lector = sqlite3.connect(db.settings.db_path)
    try:
        lector.execute("BEGIN")
        lector.execute("SELECT count(*) FROM users").fetchone()  # toma el lock

        escritor = sqlite3.connect(db.settings.db_path, timeout=0.2)
        try:
            with escritor:
                escritor.execute(
                    "CREATE TABLE IF NOT EXISTS _latido (t REAL)"
                )
                escritor.execute("INSERT INTO _latido VALUES (?)", (1.0,))
        except sqlite3.OperationalError as error:  # pragma: no cover
            pytest.fail(f"el lector bloqueó la escritura: {error}")
        finally:
            escritor.close()
    finally:
        lector.rollback()
        lector.close()

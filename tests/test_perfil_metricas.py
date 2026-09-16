import time

import pytest

from app import db, perfil, perfil_metricas as metricas


DIA = 86_400


def test_tasa_de_aceptacion():
    assert metricas.tasa_de_aceptacion(propuestas=10, aprobadas=4) == pytest.approx(0.4)
    assert metricas.tasa_de_aceptacion(propuestas=0, aprobadas=0) == 0.0


def test_supervivencia_no_cuenta_un_uso_solo_el_dia_de_instalacion():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("m1", "mcp", "viva/uno", "x")
    perfil.aprobar_capacidad("m1", "mcp", "muerta/dos", "x")
    perfil.registrar_uso_capacidad("m1", "mcp", "viva/uno")

    assert metricas.supervivencia("m1", dias=14, ahora=time.time() + 15 * DIA) == pytest.approx(0.0)


def test_supervivencia_cuenta_el_uso_sostenido_tras_el_plazo():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("m4", "skill", "viva", "x")
    with db._conn() as c:
        aprobada = c.execute(
            "SELECT aprobada_en FROM perfil_capacidades WHERE user_id='m4'"
        ).fetchone()[0]
        c.execute(
            "UPDATE perfil_capacidades SET usos=1, ultimo_uso=? WHERE user_id='m4'",
            (aprobada + 15 * DIA,),
        )
    assert metricas.supervivencia(
        "m4", dias=14, ahora=aprobada + 16 * DIA
    ) == pytest.approx(1.0)


def test_solo_cuentan_las_aprobadas_hace_mas_del_plazo():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("m2", "mcp", "recien/uno", "x")

    # Aprobada hoy: todavía no ha tenido dos semanas para demostrar nada.
    assert metricas.supervivencia("m2", dias=14) == 0.0


def test_sin_capacidades_la_supervivencia_es_cero_y_no_revienta():
    perfil.crear_tablas()

    assert metricas.supervivencia("m3", dias=14) == 0.0

import time

import pytest

from app import perfil, perfil_metricas as metricas


DIA = 86_400


def test_tasa_de_aceptacion():
    assert metricas.tasa_de_aceptacion(propuestas=10, aprobadas=4) == pytest.approx(0.4)
    assert metricas.tasa_de_aceptacion(propuestas=0, aprobadas=0) == 0.0


def test_supervivencia_cuenta_las_usadas_despues_del_plazo():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("m1", "mcp", "viva/uno", "x")
    perfil.aprobar_capacidad("m1", "mcp", "muerta/dos", "x")
    perfil.registrar_uso_capacidad("m1", "mcp", "viva/uno")

    assert metricas.supervivencia("m1", dias=14, ahora=time.time() + 15 * DIA) == pytest.approx(0.5)


def test_solo_cuentan_las_aprobadas_hace_mas_del_plazo():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("m2", "mcp", "recien/uno", "x")

    # Aprobada hoy: todavía no ha tenido dos semanas para demostrar nada.
    assert metricas.supervivencia("m2", dias=14) == 0.0


def test_sin_capacidades_la_supervivencia_es_cero_y_no_revienta():
    perfil.crear_tablas()

    assert metricas.supervivencia("m3", dias=14) == 0.0

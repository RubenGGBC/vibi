import pytest
import time
from app import perfil, perfil_observador as observador


def test_las_capacidades_nunca_usadas_salen_listadas():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("o1", "mcp", "a/uno", "x")
    perfil.aprobar_capacidad("o1", "mcp", "b/dos", "x")
    perfil.registrar_uso_capacidad("o1", "mcp", "a/uno")
    senales = observador.leer_senales("o1", desde=0)
    assert ("mcp", "b/dos") in senales.capacidades_sin_usar
    assert ("mcp", "a/uno") not in senales.capacidades_sin_usar


def test_las_recetas_cuentan_como_apps_que_se_manejan():
    perfil.crear_tablas()
    from app import recetas
    recetas.crear_tablas()
    recetas.guardar("whatsapp", "cdp", "mapa de la interfaz", comprobacion="abrí un chat")
    senales = observador.leer_senales("o2", desde=0)
    assert "whatsapp" in senales.apps_con_receta


def test_sin_nada_que_leer_las_senales_vienen_vacias():
    perfil.crear_tablas()
    senales = observador.leer_senales("o3", desde=time.time() + 1000)
    assert senales.herramientas_usadas == {}
    assert senales.capacidades_sin_usar == ()

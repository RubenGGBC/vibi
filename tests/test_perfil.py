import pytest
from app import perfil, db

@pytest.fixture(autouse=True)
def limpiar_afirmaciones():
    """Limpia la tabla de afirmaciones antes de cada test."""
    perfil.crear_tablas()
    with db._conn() as c:
        c.execute("DELETE FROM perfil_afirmaciones")
    yield

def test_afirmar_guarda_con_la_confianza_de_su_procedencia():
    hecho = perfil.afirmar("u1", "dominio", "medicina", "entrevista")
    assert hecho["valor"] == "medicina"
    assert hecho["confianza"] == pytest.approx(0.6)

def test_el_inventario_entra_con_menos_confianza_que_la_entrevista():
    perfil.afirmar("u1", "dominio", "medicina", "inventario")
    guardada = perfil.afirmaciones_de("u1")[0]
    assert guardada["confianza"] == pytest.approx(0.4)

def test_afirmar_dos_veces_lo_mismo_no_duplica():
    perfil.afirmar("u1", "dominio", "medicina", "inventario")
    perfil.afirmar("u1", "dominio", "medicina", "entrevista")
    assert len(perfil.afirmaciones_de("u1")) == 1

def test_una_clase_desconocida_es_un_error():
    with pytest.raises(perfil.PerfilInvalido):
        perfil.afirmar("u1", "signo-zodiacal", "acuario", "entrevista")

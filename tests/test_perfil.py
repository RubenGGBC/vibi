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

def test_el_uso_sube_la_confianza_y_cuenta_el_apoyo():
    perfil.crear_tablas()
    perfil.afirmar("u2", "dominio", "medicina", "inventario")
    perfil.apoyar("u2", "dominio", "medicina")
    a = perfil.afirmaciones_de("u2")[0]
    assert a["confianza"] == pytest.approx(0.5)
    assert a["apoyos"] == 1

def test_la_confianza_no_pasa_de_uno():
    perfil.crear_tablas()
    perfil.afirmar("u3", "dominio", "medicina", "uso")
    for _ in range(10):
        perfil.apoyar("u3", "dominio", "medicina")
    assert perfil.afirmaciones_de("u3")[0]["confianza"] == pytest.approx(1.0)

def test_la_contradiccion_pesa_tres_veces_mas_que_un_apoyo():
    perfil.crear_tablas()
    perfil.afirmar("u4", "dominio", "medicina", "entrevista")
    perfil.contradecir("u4", "dominio", "medicina")
    a = perfil.afirmaciones_de("u4")[0]
    assert a["confianza"] == pytest.approx(0.3)
    assert a["contras"] == 1

def test_la_confianza_no_baja_de_cero():
    perfil.crear_tablas()
    perfil.afirmar("u5", "dominio", "medicina", "inventario")
    for _ in range(5):
        perfil.contradecir("u5", "dominio", "medicina")
    assert perfil.afirmaciones_de("u5")[0]["confianza"] == pytest.approx(0.0)

def test_decaer_solo_toca_lo_que_no_se_ha_usado():
    perfil.crear_tablas()
    perfil.afirmar("u6", "dominio", "medicina", "entrevista")
    perfil.afirmar("u6", "dominio", "musica", "entrevista")
    perfil.decaer("u6", sin_uso=[("dominio", "musica")])
    por_valor = {a["valor"]: a["confianza"] for a in perfil.afirmaciones_de("u6")}
    assert por_valor["medicina"] == pytest.approx(0.6)
    assert por_valor["musica"] == pytest.approx(0.55)

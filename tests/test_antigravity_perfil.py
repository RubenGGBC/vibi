# tests/test_antigravity_perfil.py
from app.executors import antigravity_chat as motor


def test_el_bloque_se_inserta_al_final_si_no_estaba():
    resultado = motor.fusionar_reglas("Eres Vibi.\n", "Se dedica a: medicina.")
    assert "Eres Vibi." in resultado
    assert "medicina" in resultado
    assert motor.MARCA_INICIO in resultado


def test_reescribir_no_duplica_el_bloque():
    una = motor.fusionar_reglas("Eres Vibi.\n", "Se dedica a: medicina.")
    dos = motor.fusionar_reglas(una, "Se dedica a: derecho.")
    assert dos.count(motor.MARCA_INICIO) == 1
    assert "derecho" in dos
    assert "medicina" not in dos


def test_no_se_toca_nada_fuera_de_las_marcas():
    original = "Eres Vibi.\nHabla en espanol.\n"
    resultado = motor.fusionar_reglas(original, "Se dedica a: medicina.")
    assert resultado.startswith(original)


def test_un_resumen_vacio_borra_el_bloque():
    con = motor.fusionar_reglas("Eres Vibi.\n", "Se dedica a: medicina.")
    sin = motor.fusionar_reglas(con, "")
    assert motor.MARCA_INICIO not in sin
    assert sin.startswith("Eres Vibi.")

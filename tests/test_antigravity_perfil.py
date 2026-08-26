# tests/test_antigravity_perfil.py
from app import perfil
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


# A partir de aquí, el punto de entrada real: `escribir_reglas`, no
# `fusionar_reglas` a pelo. Es lo que demuestra que el cableado hasta la base
# de datos existe y que un usuario sin perfil todavía no nota nada.


def test_sin_datos_de_perfil_las_reglas_quedan_exactamente_igual(tmp_path):
    """Hoy todos los usuarios están así: sin una sola afirmación guardada.

    El comportamiento seguro no es «un bloque vacío», es «ningún bloque»: el
    archivo que sale con `user_id` de un perfil en blanco tiene que ser
    idéntico, carácter a carácter, al que salía antes de que esta tarea
    existiera.
    """
    perfil.crear_tablas()
    sin_user_id = tmp_path / "sin_user_id"
    con_perfil_vacio = tmp_path / "con_perfil_vacio"
    sin_user_id.mkdir()
    con_perfil_vacio.mkdir()

    motor.escribir_reglas(sin_user_id, "Ruben")
    motor.escribir_reglas(con_perfil_vacio, "Ruben", user_id="usuario-sin-perfil-aun")

    antes = (sin_user_id / motor.ARCHIVO_REGLAS).read_text(encoding="utf-8")
    despues = (con_perfil_vacio / motor.ARCHIVO_REGLAS).read_text(encoding="utf-8")
    assert antes == despues
    assert motor.MARCA_INICIO not in despues


def test_con_perfil_de_verdad_las_reglas_llevan_el_resumen(tmp_path):
    perfil.crear_tablas()
    perfil.afirmar("usuario-medico", "dominio", "medicina", "entrevista")

    motor.escribir_reglas(tmp_path, "Ruben", user_id="usuario-medico")

    contenido = (tmp_path / motor.ARCHIVO_REGLAS).read_text(encoding="utf-8")
    assert motor.MARCA_INICIO in contenido
    assert "medicina" in contenido


def test_si_leer_el_perfil_falla_las_reglas_se_escriben_igual_sin_el_bloque(
    tmp_path, monkeypatch
):
    """Una consulta a la base que revienta no puede tumbar el arranque del motor.

    Quedarse sin especialización es aceptable; quedarse sin conversación no.
    """
    perfil.crear_tablas()

    def _revienta(*args, **kwargs):
        raise RuntimeError("la base no responde")

    monkeypatch.setattr(perfil, "afirmaciones_de", _revienta)

    motor.escribir_reglas(tmp_path, "Ruben", user_id="usuario-cualquiera")

    contenido = (tmp_path / motor.ARCHIVO_REGLAS).read_text(encoding="utf-8")
    assert "Vibi" in contenido
    assert motor.MARCA_INICIO not in contenido

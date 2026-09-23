# tests/test_antigravity_perfil.py
from app import perfil
from app.executors import antigravity_chat as motor
from app.executors import agy_client


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


# Marcas rotas: `GEMINI.md` es un archivo que también puede editar una
# persona a mano, así que una apertura sin cierre, un cierre sin apertura o
# las dos en el orden que no toca no pueden dejar un `MARCA_INICIO`
# duplicado ni comerse texto que no es del bloque.


def test_una_apertura_sin_cierre_no_deja_dos_marcas():
    roto = "Eres Vibi.\n" + motor.MARCA_INICIO + "\nlo que fuera\n"
    resultado = motor.fusionar_reglas(roto, "Se dedica a: medicina.")
    assert resultado.count(motor.MARCA_INICIO) == 1
    assert "Eres Vibi." in resultado
    assert "medicina" in resultado


def test_un_cierre_sin_apertura_se_quita_pero_conserva_el_resto():
    roto = "Eres Vibi.\n" + motor.MARCA_FIN + "\notro texto\n"
    resultado = motor.fusionar_reglas(roto, "Se dedica a: medicina.")
    assert resultado.count(motor.MARCA_INICIO) == 1
    assert resultado.count(motor.MARCA_FIN) == 1
    assert "Eres Vibi." in resultado
    assert "otro texto" in resultado
    assert "medicina" in resultado


def test_las_marcas_en_orden_invertido_no_duplican_nada():
    roto = (
        "Eres Vibi.\n"
        + motor.MARCA_FIN
        + "\nmedio\n"
        + motor.MARCA_INICIO
        + "\ncola rota"
    )
    resultado = motor.fusionar_reglas(roto, "Se dedica a: medicina.")
    assert resultado.count(motor.MARCA_INICIO) == 1
    assert resultado.count(motor.MARCA_FIN) == 1
    assert "Eres Vibi." in resultado
    assert "medio" in resultado
    assert "cola rota" not in resultado
    assert "medicina" in resultado


def test_marcas_rotas_con_resumen_vacio_no_dejan_ningun_bloque():
    roto = "Eres Vibi.\n" + motor.MARCA_INICIO + "\nlo que fuera\n"
    resultado = motor.fusionar_reglas(roto, "")
    assert motor.MARCA_INICIO not in resultado
    assert motor.MARCA_FIN not in resultado
    assert "Eres Vibi." in resultado


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


def test_un_mcp_dinamico_que_aparece_en_el_stream_registra_su_uso():
    perfil.crear_tablas()
    perfil.aprobar_capacidad(
        "usuario-mcp", "mcp", "a/pdf", "Lee PDF", transporte="remoto",
        endpoint="https://example.test/mcp",
    )
    vistos: set[str] = set()
    motor._registrar_usos_mcp_perfil(
        "usuario-mcp",
        (),
        (agy_client.Paso("CORTEX_STEP_TYPE_MCP_TOOL", "CORTEX_STEP_STATUS_RUNNING", "a/pdf: read"),),
        vistos,
    )
    motor._registrar_usos_mcp_perfil(
        "usuario-mcp",
        (),
        (agy_client.Paso("CORTEX_STEP_TYPE_MCP_TOOL", "CORTEX_STEP_STATUS_DONE", "a/pdf: read"),),
        vistos,
    )
    assert perfil.capacidades_de("usuario-mcp")[0]["usos"] == 1


def test_el_nombre_normalizado_por_agy_tambien_registra_el_uso_mcp():
    perfil.crear_tablas()
    perfil.aprobar_capacidad(
        "usuario-mcp-normalizado", "mcp", "ai.pdfassistant/pdf-assistant",
        "Lee PDF", transporte="remoto", endpoint="https://example.test/mcp",
    )
    motor._registrar_usos_mcp_perfil(
        "usuario-mcp-normalizado",
        (("mcp__ai_pdfassistant_pdf_assistant__read", "CORTEX_STEP_STATUS_DONE"),),
        (),
        set(),
    )
    assert perfil.capacidades_de("usuario-mcp-normalizado")[0]["usos"] == 1


def test_el_bloque_de_reglas_cuenta_como_es_la_persona(tmp_path):
    """La queja que abrió esta tarea: el bloque solo hablaba de aficiones."""
    perfil.crear_tablas()
    perfil.afirmar("usuario-rasgo", "dominio", "ingeniería informática", "entrevista")
    perfil.afirmar(
        "usuario-rasgo", "rasgo",
        "directo, se aburre con las explicaciones largas", "entrevista",
    )
    perfil.afirmar("usuario-rasgo", "aficion", "videojuegos", "entrevista")

    motor.escribir_reglas(tmp_path, "Ruben", user_id="usuario-rasgo")

    contenido = (tmp_path / motor.ARCHIVO_REGLAS).read_text(encoding="utf-8")
    bloque = contenido.split(motor.MARCA_INICIO)[1].split(motor.MARCA_FIN)[0]
    lineas = [linea for linea in bloque.splitlines() if linea.startswith(("Se ", "Es", "Le "))]
    assert lineas == [
        "Se dedica a: ingeniería informática.",
        "Es: directo, se aburre con las explicaciones largas.",
        "Le interesa: videojuegos.",
    ]

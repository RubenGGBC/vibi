import pytest
import time
from app import perfil, perfil_observador as observador, db
from app import recetas


@pytest.fixture(autouse=True)
def limpiar_observador():
    """Limpia tablas antes de cada test para aislarlos."""
    perfil.crear_tablas()
    recetas.crear_tablas()
    with db._conn() as c:
        c.execute("DELETE FROM tool_invocations")
        c.execute("DELETE FROM recetas")
        c.execute("DELETE FROM perfil_capacidades")
        c.execute("DELETE FROM perfil_afirmaciones")
        c.execute("DELETE FROM users")
    yield


def _crear_usuario(user_id: str) -> None:
    """Crea un usuario para poder insertar invocaciones."""
    with db._conn() as c:
        c.execute(
            "INSERT INTO users (id, nombre, creado_en) VALUES (?, ?, ?)",
            (user_id, f"usuario_{user_id}", time.time()),
        )


def test_las_capacidades_nunca_usadas_salen_listadas():
    perfil.aprobar_capacidad("o1", "mcp", "a/uno", "x")
    perfil.aprobar_capacidad("o1", "mcp", "b/dos", "x")
    perfil.registrar_uso_capacidad("o1", "mcp", "a/uno")
    senales = observador.leer_senales("o1", desde=0)
    assert ("mcp", "b/dos") in senales.capacidades_sin_usar
    assert ("mcp", "a/uno") not in senales.capacidades_sin_usar


def test_las_recetas_cuentan_como_apps_que_se_manejan():
    recetas.guardar("whatsapp", "cdp", "mapa de la interfaz", comprobacion="abrí un chat")
    senales = observador.leer_senales("o2", desde=0)
    assert "whatsapp" in senales.apps_con_receta


def test_sin_nada_que_leer_las_senales_vienen_vacias():
    senales = observador.leer_senales("o3", desde=time.time() + 1000)
    assert senales.herramientas_usadas == {}
    assert senales.apps_con_receta == ()
    assert senales.capacidades_sin_usar == ()


def test_una_invocacion_dentro_del_periodo_se_cuenta():
    _crear_usuario("o4")
    ahora = time.time()
    with db._conn() as c:
        c.execute(
            """INSERT INTO tool_invocations
               (id, tool_id, actor_user_id, status, requested_at)
               VALUES (?, ?, ?, 'succeeded', ?)""",
            ("inv1", "navegador/abrir", "o4", ahora),
        )
    senales = observador.leer_senales("o4", desde=ahora - 1)
    assert senales.herramientas_usadas.get("navegador/abrir") == 1


def test_una_invocacion_anterior_al_periodo_no_se_cuenta():
    _crear_usuario("o5")
    ahora = time.time()
    anterior = ahora - 100
    with db._conn() as c:
        c.execute(
            """INSERT INTO tool_invocations
               (id, tool_id, actor_user_id, status, requested_at)
               VALUES (?, ?, ?, 'succeeded', ?)""",
            ("inv2", "navegador/abrir", "o5", anterior),
        )
    senales = observador.leer_senales("o5", desde=ahora - 1)
    assert senales.herramientas_usadas.get("navegador/abrir") is None


def test_una_invocacion_de_otro_usuario_no_se_cuenta():
    _crear_usuario("otro_usuario")
    _crear_usuario("o6")
    ahora = time.time()
    with db._conn() as c:
        c.execute(
            """INSERT INTO tool_invocations
               (id, tool_id, actor_user_id, status, requested_at)
               VALUES (?, ?, ?, 'succeeded', ?)""",
            ("inv3", "navegador/abrir", "otro_usuario", ahora),
        )
    senales = observador.leer_senales("o6", desde=ahora - 1)
    assert senales.herramientas_usadas.get("navegador/abrir") is None


def test_una_capacidad_sin_usar_baja_de_nivel():
    perfil.afirmar("o7", "herramienta", "pdf", "entrevista")
    perfil.aprobar_capacidad("o7", "mcp", "a/pdf", "Lee PDF")
    senales = observador.Senales({}, (), (("mcp", "a/pdf"),))

    # Cuatro revisiones sin uso: 0,6 → 0,4 → nivel catálogo.
    for _ in range(4):
        observador.revisar("o7", senales)

    capacidad = [
        c for c in perfil.capacidades_de("o7") if c["referencia"] == "a/pdf"
    ][0]
    assert capacidad["nivel"] == "catalogo"


def test_una_app_con_receta_apoya_su_afirmacion():
    perfil.afirmar("o8", "herramienta", "whatsapp", "inventario")
    senales = observador.Senales({}, ("whatsapp",), ())

    observador.revisar("o8", senales)

    afirmacion = [
        item for item in perfil.afirmaciones_de("o8") if item["valor"] == "whatsapp"
    ][0]
    assert afirmacion["confianza"] == pytest.approx(0.5)


def test_la_revision_informa_de_lo_que_ha_movido():
    perfil.afirmar("o9", "herramienta", "whatsapp", "inventario")

    resultado = observador.revisar(
        "o9", observador.Senales({}, ("whatsapp",), ())
    )

    assert "whatsapp" in resultado["apoyadas"]

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


def test_una_capacidad_aprobada_durante_el_periodo_no_decae_aun():
    desde = time.time()
    perfil.aprobar_capacidad("o11", "skill", "nueva", "Acaba de aprobarse")

    senales = observador.leer_senales("o11", desde=desde)

    assert ("skill", "nueva") not in senales.capacidades_sin_usar


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


def test_la_confianza_caida_empeora_el_veredicto_del_desuso():
    """Con una afirmación que la sostiene, la capacidad no espera a la escalera.

    Una sola revisión sin uso no daría para bajar de nivel por desuso, pero la
    afirmación que justificaba la capacidad nació floja —del inventario, 0,4— y
    la revisión la deja en 0,35: manda la peor de las dos lecturas.
    """
    perfil.afirmar("o7", "herramienta", "pdf", "inventario")
    perfil.aprobar_capacidad("o7", "mcp", "a/pdf", "Lee pdf del usuario")
    senales = observador.Senales({}, (), (("mcp", "a/pdf"),))

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


def test_la_revision_informa_tambien_de_lo_decaido_y_lo_propuesto():
    """El contrato de revisar() promete tres listas, no una.

    Un test que solo mirara «apoyadas» no delataría que se dejaran de
    rellenar «decaidas» o «propuestas_retirada» — hallazgo de la revisión
    de esta tarea.
    """
    perfil.aprobar_capacidad("o10", "mcp", "a/sinrelacion", "Sin afirmacion que lo sostenga")
    senales = observador.Senales({}, (), (("mcp", "a/sinrelacion"),))

    for _ in range(perfil.DESUSO_A_RETIRADA - 1):
        intermedio = observador.revisar("o10", senales)
        assert "a/sinrelacion" in intermedio["decaidas"]
        assert intermedio["propuestas_retirada"] == []
    resultado = observador.revisar("o10", senales)

    assert "a/sinrelacion" in resultado["decaidas"]
    assert "a/sinrelacion" in resultado["propuestas_retirada"]


def test_una_capacidad_sin_usar_baja_un_escalon_por_revision():
    """La retirada se propone tras tres revisiones, no en la primera.

    El nivel es el del desuso acumulado, no el de una justificación que casi
    nunca casa con lo que el usuario dijo: la justificación viene del registro
    público y está en inglés.
    """
    perfil.aprobar_capacidad("o20", "mcp", "vendor/sin-usar", "Reads PDF files")
    senales = observador.Senales(
        herramientas_usadas={},
        apps_con_receta=(),
        capacidades_sin_usar=(("mcp", "vendor/sin-usar"),),
    )

    def nivel():
        return next(
            c["nivel"] for c in perfil.capacidades_de("o20")
            if c["referencia"] == "vendor/sin-usar"
        )

    observador.revisar("o20", senales)
    assert nivel() == "completo"
    observador.revisar("o20", senales)
    assert nivel() == "catalogo"
    resultado = observador.revisar("o20", senales)
    assert nivel() == "propuesta_retirada"
    assert "vendor/sin-usar" in resultado["propuestas_retirada"]


def test_usar_una_capacidad_borra_el_desuso_acumulado():
    perfil.aprobar_capacidad("o21", "mcp", "vendor/intermitente", "Reads PDF files")
    sin_usar = observador.Senales(
        herramientas_usadas={},
        apps_con_receta=(),
        capacidades_sin_usar=(("mcp", "vendor/intermitente"),),
    )
    observador.revisar("o21", sin_usar)
    observador.revisar("o21", sin_usar)

    perfil.registrar_uso_capacidad("o21", "mcp", "vendor/intermitente")
    observador.revisar("o21", observador.Senales(
        herramientas_usadas={},
        apps_con_receta=(),
        capacidades_sin_usar=(),
        capacidades_usadas=(("mcp", "vendor/intermitente"),),
    ))
    observador.revisar("o21", sin_usar)

    cap = next(
        c for c in perfil.capacidades_de("o21")
        if c["referencia"] == "vendor/intermitente"
    )
    assert cap["nivel"] == "completo"


def test_una_receta_no_apoya_una_afirmacion_por_una_subcadena():
    """«word» no debe apoyarse en que el usuario maneje «wordpress»."""
    perfil.afirmar("o22", "herramienta", "word", "entrevista")
    senales = observador.Senales(
        herramientas_usadas={},
        apps_con_receta=("wordpress",),
        capacidades_sin_usar=(),
    )
    observador.revisar("o22", senales)
    afirmacion = perfil.afirmaciones_de("o22")[0]
    assert afirmacion["apoyos"] == 0

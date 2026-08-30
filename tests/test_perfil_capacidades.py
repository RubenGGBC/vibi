import pytest
from app import perfil


def test_nivel_por_umbral():
    assert perfil.nivel_para(0.9) == "completo"
    assert perfil.nivel_para(0.6) == "completo"
    assert perfil.nivel_para(0.45) == "catalogo"
    assert perfil.nivel_para(0.3) == "catalogo"
    assert perfil.nivel_para(0.1) == "propuesta_retirada"


def test_aprobar_capacidad_la_deja_completa_y_sin_usos():
    perfil.crear_tablas()
    cap = perfil.aprobar_capacidad(
        "u1", "mcp", "ai.pdfassistant/pdfassistant",
        "Lee y convierte los PDF de tus apuntes", transporte="remoto",
        endpoint="https://chat.pdfassistant.ai/mcp",
    )
    assert cap["nivel"] == "completo"
    assert cap["usos"] == 0
    assert cap["aprobada_en"] is not None


def test_registrar_uso_cuenta_y_marca_la_fecha():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("u2", "skill", "resumir-paper", "Resume papers")
    perfil.registrar_uso_capacidad("u2", "skill", "resumir-paper")
    cap = next(
        capacidad
        for capacidad in perfil.capacidades_de("u2")
        if capacidad["referencia"] == "resumir-paper"
    )
    assert cap["usos"] == 1
    assert cap["ultimo_uso"] is not None


def test_un_tipo_desconocido_es_un_error():
    perfil.crear_tablas()
    with pytest.raises(perfil.PerfilInvalido):
        perfil.aprobar_capacidad("u3", "plugin", "lo-que-sea", "porque si")


def test_una_capacidad_sin_justificacion_es_un_error():
    perfil.crear_tablas()
    with pytest.raises(perfil.PerfilInvalido):
        perfil.aprobar_capacidad("u4", "mcp", "algo/algo", "")


def test_el_endpoint_se_guarda_para_poder_declarar_el_servidor():
    perfil.crear_tablas()
    perfil.aprobar_capacidad(
        "u9", "mcp", "ai.pdfassistant/pdfassistant", "Lee tus PDF",
        transporte="remoto", endpoint="https://chat.pdfassistant.ai/mcp",
    )
    cap = perfil.capacidades_de("u9")[0]
    assert cap["endpoint"] == "https://chat.pdfassistant.ai/mcp"


def test_borrar_un_mcp_conserva_una_tumba_para_retirarlo_del_motor():
    perfil.crear_tablas()
    cap = perfil.aprobar_capacidad(
        "u10", "mcp", "a/pdf", "Lee PDF", transporte="remoto",
        endpoint="https://example.test/mcp",
    )
    assert perfil.eliminar_capacidad("u10", cap["id"]) is True
    assert perfil.mcp_retirados_de("u10") == ("a/pdf",)


def test_borrar_una_skill_conserva_la_referencia_para_desactivarla():
    perfil.crear_tablas()
    cap = perfil.aprobar_capacidad("u13", "skill", "resumir", "Resume textos")
    assert perfil.eliminar_capacidad("u13", cap["id"]) is True
    assert perfil.capacidades_retiradas_de("u13", "skill") == ("resumir",)


def test_guardar_entrevista_valida_todo_antes_de_escribir():
    perfil.crear_tablas()
    with pytest.raises(perfil.PerfilInvalido):
        perfil.guardar_entrevista(
            "u11",
            [{"clase": "dominio", "valor": "medicina", "procedencia": "entrevista"}],
            [{"tipo": "mcp", "referencia": "a/pdf", "justificacion": "Lee PDF",
              "transporte": "remoto", "endpoint": ""}],
        )
    assert perfil.afirmaciones_de("u11") == []
    assert perfil.capacidades_de("u11") == []


def test_las_propuestas_guardan_aceptadas_y_rechazadas():
    perfil.crear_tablas()
    perfil.registrar_propuestas("u12", [
        {"tipo": "mcp", "referencia": "a/uno", "bloque": "pedido"},
        {"tipo": "mcp", "referencia": "b/dos", "bloque": "encaja"},
    ])
    perfil.resolver_propuestas("u12", {("mcp", "a/uno")})
    assert perfil.metricas_propuestas("u12") == (2, 1)


def test_guardar_entrevista_resuelve_propuestas_en_la_misma_operacion():
    perfil.crear_tablas()
    perfil.registrar_propuestas("u14", [
        {"tipo": "skill", "referencia": "a/uno", "bloque": "pedido"},
        {"tipo": "skill", "referencia": "b/dos", "bloque": "encaja"},
    ])
    perfil.guardar_entrevista(
        "u14",
        [],
        [{"tipo": "skill", "referencia": "a/uno", "justificacion": "Ayuda",
          "transporte": "", "endpoint": ""}],
    )
    assert perfil.metricas_propuestas("u14") == (2, 1)


def test_un_mcp_local_lanzable_se_puede_aprobar():
    """Decisión del 30/08/2026: los locales entran, con su paquete.

    Antes se rechazaban todos por no haber instalador. Lo que hace que uno
    sea aprobable no es el transporte sino saber arrancarlo sin pedir nada:
    eso es lo que lleva dentro `paquete`.
    """
    cap = perfil.aprobar_capacidad(
        "L1", "mcp", "io.github.Grinv/steam-games-mcp", "Datos de Steam",
        transporte="local", paquete="npm:steam-games-mcp@1.2.0",
    )
    assert cap["transporte"] == "local"
    assert cap["paquete"] == "npm:steam-games-mcp@1.2.0"


def test_un_mcp_local_sin_paquete_sigue_sin_poder_aprobarse():
    with pytest.raises(perfil.PerfilInvalido) as fallo:
        perfil.aprobar_capacidad(
            "L2", "mcp", "x/y", "Sin forma de lanzarlo", transporte="local"
        )
    assert "x/y" in str(fallo.value)


def test_la_entrevista_guarda_un_local_con_su_paquete():
    perfil.guardar_entrevista(
        "L3",
        [],
        [
            {
                "tipo": "mcp",
                "referencia": "io.github.Sarg338/steam-mcp",
                "justificacion": "Steam",
                "transporte": "local",
                "paquete": "pypi:steam-mcp@0.3.0",
            }
        ],
    )
    cap = perfil.capacidades_de("L3", "mcp")[0]
    assert cap["paquete"] == "pypi:steam-mcp@0.3.0"

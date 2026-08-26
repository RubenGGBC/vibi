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
    )
    assert cap["nivel"] == "completo"
    assert cap["usos"] == 0
    assert cap["aprobada_en"] is not None


def test_registrar_uso_cuenta_y_marca_la_fecha():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("u2", "skill", "resumir-paper", "Resume papers")
    perfil.registrar_uso_capacidad("u2", "skill", "resumir-paper")
    cap = perfil.capacidades_de("u2")[0]
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

from app import perfil
from app.executors import agy_mcp_config


def test_un_mcp_aprobado_en_completo_se_declara():
    perfil.crear_tablas()
    perfil.aprobar_capacidad(
        "u1", "mcp", "ai.pdfassistant/pdfassistant", "Lee tus PDF",
        transporte="remoto", endpoint="https://chat.pdfassistant.ai/mcp",
    )
    declarados = agy_mcp_config.del_perfil("u1")
    assert "ai.pdfassistant/pdfassistant" in declarados
    assert declarados["ai.pdfassistant/pdfassistant"] is not None


def test_un_mcp_bajado_a_catalogo_se_borra_explicitamente():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("u2", "mcp", "b/dos", "algo", transporte="remoto")
    perfil.fijar_nivel("u2", "mcp", "b/dos", "catalogo")
    declarados = agy_mcp_config.del_perfil("u2")
    assert declarados["b/dos"] is None


def test_sin_perfil_no_se_declara_nada():
    perfil.crear_tablas()
    assert agy_mcp_config.del_perfil("usuario-sin-perfil") == {}


def test_un_remoto_se_declara_con_su_url():
    perfil.crear_tablas()
    perfil.aprobar_capacidad(
        "u5", "mcp", "a/pdf", "Lee PDF",
        transporte="remoto", endpoint="https://chat.pdfassistant.ai/mcp",
    )
    declarados = agy_mcp_config.del_perfil("u5")
    assert declarados["a/pdf"] == {"serverUrl": "https://chat.pdfassistant.ai/mcp"}


def test_un_local_sin_instalar_no_se_declara():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("u6", "mcp", "b/oci", "Infra", transporte="local")
    assert agy_mcp_config.del_perfil("u6")["b/oci"] is None

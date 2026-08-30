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
    perfil.aprobar_capacidad(
        "u2", "mcp", "b/dos", "algo", transporte="remoto",
        endpoint="https://example.test/mcp",
    )
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


def test_un_local_que_no_sabemos_lanzar_no_se_puede_aprobar():
    """Los locales entran desde el 30/08/2026, pero solo los lanzables.

    Uno de `oci` o `mcpb`, o uno que exige una credencial que no tenemos,
    llega sin `paquete` y se sigue rechazando: declararlo dejaría a `agy`
    arrancando un servidor que no puede funcionar.
    """
    perfil.crear_tablas()
    import pytest
    with pytest.raises(perfil.PerfilInvalido):
        perfil.aprobar_capacidad("u6", "mcp", "b/oci", "Infra", transporte="local")


def test_un_local_lanzable_se_declara_con_su_comando():
    perfil.crear_tablas()
    perfil.aprobar_capacidad(
        "u7", "mcp", "io.github.Grinv/steam-games-mcp", "Datos de Steam",
        transporte="local", paquete="npm:steam-games-mcp@1.2.0",
    )
    declarado = agy_mcp_config.del_perfil("u7")["io.github.Grinv/steam-games-mcp"]
    # El comando exacto depende de dónde esté `npx` en esta máquina (ver
    # `_npx`), así que aquí se mira lo que sí es fijo: que se lanza con npx y
    # con la versión que se aprobó, no con «lo último que haya».
    assert "npx" in declarado["command"]
    assert declarado["args"] == ["-y", "steam-games-mcp@1.2.0"]


def test_un_local_de_npm_usa_el_npx_que_de_verdad_se_puede_lanzar(monkeypatch):
    """En este equipo `npx` del PATH es un `.ps1`, y eso no se puede lanzar.

    `agy` arranca el servidor como proceso hijo, y en Windows un `.ps1` no es
    ejecutable por sí solo. La variable ya existía para lo mismo en el nodo
    (`browser_mcp._npx`), así que aquí se lee igual en vez de inventar otra.
    """
    monkeypatch.setenv("VIBI_NPX", r"C:\node\npx.cmd")
    perfil.crear_tablas()
    perfil.aprobar_capacidad(
        "u8", "mcp", "a/npmlocal", "algo",
        transporte="local", paquete="npm:algo-mcp@1.0.0",
    )
    declarado = agy_mcp_config.del_perfil("u8")["a/npmlocal"]
    assert declarado["command"] == r"C:\node\npx.cmd"
    assert declarado["args"] == ["-y", "algo-mcp@1.0.0"]


def test_un_local_de_pypi_no_depende_de_esa_variable(monkeypatch):
    monkeypatch.setenv("VIBI_NPX", r"C:\node\npx.cmd")
    perfil.crear_tablas()
    perfil.aprobar_capacidad(
        "u9", "mcp", "a/pypilocal", "algo",
        transporte="local", paquete="pypi:algo-mcp@2.0.0",
    )
    declarado = agy_mcp_config.del_perfil("u9")["a/pypilocal"]
    assert declarado["command"] == "uvx"

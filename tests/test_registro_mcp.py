import httpx
import pytest

from app import registro_mcp

RESPUESTA = {
    "servers": [
        {
            "server": {
                "name": "ai.pdfassistant/pdfassistant",
                "title": "pdfAssistant",
                "description": "Convert, merge, compress, OCR PDFs",
                "version": "1.35.17",
                "websiteUrl": "https://pdfassistant.ai",
                "remotes": [{"type": "streamable-http", "url": "https://chat.pdfassistant.ai/mcp"}],
            },
            "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active"}},
        },
        {
            "server": {
                "name": "cloud.massdriver/mcp-server",
                "title": "Massdriver",
                "description": "Infra",
                "version": "1.0.0",
                "packages": [{"registryType": "oci"}],
            },
            "_meta": {"io.modelcontextprotocol.registry/official": {"status": "deleted"}},
        },
    ]
}

def test_interpretar_distingue_remoto_de_local():
    servidores = registro_mcp.interpretar(RESPUESTA)
    por_nombre = {s.nombre: s for s in servidores}
    assert por_nombre["ai.pdfassistant/pdfassistant"].transporte == "remoto"
    assert por_nombre["cloud.massdriver/mcp-server"].transporte == "local"

def test_interpretar_marca_los_que_no_estan_activos():
    por_nombre = {s.nombre: s for s in registro_mcp.interpretar(RESPUESTA)}
    assert por_nombre["ai.pdfassistant/pdfassistant"].activo is True
    assert por_nombre["cloud.massdriver/mcp-server"].activo is False

def test_un_servidor_sin_transporte_no_se_devuelve():
    payload = {"servers": [{"server": {"name": "x/y", "description": "d", "version": "1"},
                            "_meta": {}}]}
    assert registro_mcp.interpretar(payload) == []

def test_una_respuesta_rota_no_revienta():
    assert registro_mcp.interpretar({}) == []
    assert registro_mcp.interpretar({"servers": None}) == []


def test_interpretar_descarta_un_remoto_sin_endpoint():
    payload = {
        "servers": [
            {
                "server": {
                    "name": "x/y",
                    "description": "d",
                    "version": "1",
                    "remotes": [{"type": "http"}],
                },
                "_meta": {"io.modelcontextprotocol.registry/official": "active"},  # string, no dict
            }
        ]
    }
    servidores = registro_mcp.interpretar(payload)
    assert servidores == []


def test_interpretar_conserva_el_endpoint_mcp_y_no_la_web_comercial():
    servidor = registro_mcp.interpretar(RESPUESTA)[0]
    assert servidor.endpoint == "https://chat.pdfassistant.ai/mcp"
    assert servidor.web == "https://pdfassistant.ai"


def test_buscar_con_respuesta_buena():
    """buscar() devuelve solo servidores activos."""
    transporte = httpx.MockTransport(
        lambda req: httpx.Response(200, json=RESPUESTA)
    )
    cliente = httpx.Client(transport=transporte)
    result = registro_mcp.buscar("pdf", cliente=cliente)
    assert len(result) == 1
    assert result[0].nombre == "ai.pdfassistant/pdfassistant"
    assert result[0].activo is True


def test_buscar_con_error_http():
    """buscar() devuelve [] ante error HTTP."""
    transporte = httpx.MockTransport(
        lambda req: httpx.Response(500, text="Internal Server Error")
    )
    cliente = httpx.Client(transport=transporte)
    result = registro_mcp.buscar("pdf", cliente=cliente)
    assert result == []


def test_buscar_con_cuerpo_no_json():
    """buscar() devuelve [] si el cuerpo no es JSON válido."""
    transporte = httpx.MockTransport(
        lambda req: httpx.Response(200, text="<html>Maintenance</html>")
    )
    cliente = httpx.Client(transport=transporte)
    result = registro_mcp.buscar("pdf", cliente=cliente)
    assert result == []


def test_buscar_con_excepcion_de_transporte():
    """buscar() devuelve [] si httpx lanza excepción."""
    def failing_transport(req):
        raise httpx.ConnectError("Connection failed")

    transporte = httpx.MockTransport(failing_transport)
    cliente = httpx.Client(transport=transporte)
    result = registro_mcp.buscar("pdf", cliente=cliente)
    assert result == []


def test_un_servidor_inactivo_no_pasa_la_verificacion():
    s = registro_mcp.Servidor("a/b", "A", "d", "1", "", "remoto", activo=False)
    vale, motivo = registro_mcp.verificar(s, sonda=lambda _: True)
    assert vale is False
    assert "activo" in motivo


def test_un_servidor_que_no_responde_no_pasa():
    s = registro_mcp.Servidor("a/b", "A", "d", "1", "", "remoto", activo=True)
    vale, motivo = registro_mcp.verificar(s, sonda=lambda _: False)
    assert vale is False
    assert "responde" in motivo


def test_un_servidor_activo_que_responde_pasa():
    s = registro_mcp.Servidor("a/b", "A", "d", "1", "", "remoto", activo=True)
    vale, motivo = registro_mcp.verificar(s, sonda=lambda _: True)
    assert vale is True
    assert motivo == ""


def test_la_sonda_que_revienta_cuenta_como_no_responde():
    def sonda_rota(_):
        raise RuntimeError("boom")
    s = registro_mcp.Servidor("a/b", "A", "d", "1", "", "local", activo=True)
    vale, _ = registro_mcp.verificar(s, sonda=sonda_rota)
    assert vale is False


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_la_sonda_real_no_acepta_respuestas_http_de_error(monkeypatch, status):
    servidor = registro_mcp.Servidor(
        "a/b", "A", "d", "1", "", "remoto", True,
        "https://example.test/mcp",
    )
    monkeypatch.setattr(
        registro_mcp.httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            status, headers={"content-type": "application/json"}
        ),
    )
    assert registro_mcp._sonda_por_defecto(servidor) is False


def test_la_sonda_real_exige_una_respuesta_mcp(monkeypatch):
    servidor = registro_mcp.Servidor(
        "a/b", "A", "d", "1", "", "remoto", True,
        "https://example.test/mcp",
    )
    monkeypatch.setattr(
        registro_mcp.httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            200, headers={"content-type": "text/html"}
        ),
    )
    assert registro_mcp._sonda_por_defecto(servidor) is False

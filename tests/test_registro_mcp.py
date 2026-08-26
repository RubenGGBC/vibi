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


def test_interpretar_defensivo_con_meta_no_dict():
    """Si _meta[CLAVE_META] no es dict, no revienta."""
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
    assert len(servidores) == 1
    assert servidores[0].activo is False  # no coincide "active" != status


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

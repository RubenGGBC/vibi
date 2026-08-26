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

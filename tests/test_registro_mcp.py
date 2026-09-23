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


def test_buscar_pide_solo_la_ultima_version_de_cada_servidor():
    """Sin `version=latest` el registro devuelve una entrada por versión.

    Medido contra el registro real el 30/08/2026: `search=email` sin el
    parámetro devolvía 20 entradas que eran 6 servidores distintos —siete de
    ellas la misma—, y con él, 20 servidores distintos. El límite se gastaba
    en repetir, así que cada consulta veía un tercio del catálogo.
    """
    vistas: list[httpx.QueryParams] = []

    def espiar(req: httpx.Request) -> httpx.Response:
        vistas.append(req.url.params)
        return httpx.Response(200, json=RESPUESTA)

    cliente = httpx.Client(transport=httpx.MockTransport(espiar))
    registro_mcp.buscar("email", cliente=cliente)

    assert vistas[0].get("version") == "latest"


def _servidor(nombre, titulo="", descripcion=""):
    return registro_mcp.Servidor(
        nombre=nombre,
        titulo=titulo or nombre,
        descripcion=descripcion,
        version="1",
        web="",
        transporte="remoto",
        activo=True,
        endpoint="https://ejemplo/mcp",
    )


def test_lo_que_solo_coincide_en_el_publicador_no_es_relevante():
    """El caso que colaba trading de Robinhood buscando «gaming».

    El registro busca por texto plano sobre el registro entero, así que el
    nombre de quien publica cuenta como coincidencia. `KunaniGaming` no hace
    que un servidor de prompts de bolsa tenga nada que ver con los juegos.
    """
    ruido = _servidor(
        "io.github.KunaniGaming/agentic-prompt",
        descripcion="1,177 free agentic trading prompts for Claude and Robinhood",
    )
    assert registro_mcp.relevancia(ruido, "gaming") == 0.0


def test_el_termino_en_el_nombre_pesa_mas_que_en_la_descripcion():
    por_nombre = _servidor("com.soren/games", descripcion="Precios en varias tiendas")
    por_descripcion = _servidor(
        "com.otro/catalogo", descripcion="Catálogo de games para consolas"
    )
    assert registro_mcp.relevancia(por_nombre, "games") > registro_mcp.relevancia(
        por_descripcion, "games"
    )
    assert registro_mcp.relevancia(por_descripcion, "games") > 0.0


def test_la_relevancia_casa_por_palabra_y_no_por_subcadena():
    """Misma trampa que ya se corrigió en las recetas: «word» y «wordpress»."""
    ajeno = _servidor("com.ejemplo/wordpress", descripcion="Publica en WordPress")
    assert registro_mcp.relevancia(ajeno, "word") == 0.0


LOCAL_NPM = {
    "servers": [
        {
            "server": {
                "name": "io.github.Grinv/steam-games-mcp",
                "title": "Steam Games",
                "description": "Steam store data",
                "version": "1.0.0",
                "packages": [
                    {
                        "registryType": "npm",
                        "identifier": "steam-games-mcp",
                        "version": "1.2.0",
                        "transport": {"type": "stdio"},
                    }
                ],
            },
            "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active"}},
        }
    ]
}


def test_un_local_de_npm_conserva_como_se_lanza():
    servidor = registro_mcp.interpretar(LOCAL_NPM)[0]
    assert servidor.transporte == "local"
    assert servidor.paquete == "npm:steam-games-mcp@1.2.0"


def test_un_local_que_exige_credencial_no_se_da_por_lanzable():
    """Declarar uno sin su clave deja a `agy` arrancando un servidor muerto.

    Pedirle la clave al usuario es otra pantalla que todavía no existe, así
    que hasta entonces se marca como no lanzable y `verificar` lo rechaza con
    un motivo que se puede leer.
    """
    payload = {
        "servers": [
            {
                "server": {
                    "name": "io.github.jamiew/spotify-mcp",
                    "title": "Spotify",
                    "description": "Spotify control",
                    "version": "1.0.0",
                    "packages": [
                        {
                            "registryType": "npm",
                            "identifier": "spotify-mcp",
                            "version": "1.0.0",
                            "environmentVariables": [
                                {"name": "SPOTIFY_CLIENT_ID", "isRequired": True}
                            ],
                        }
                    ],
                },
                "_meta": {
                    "io.modelcontextprotocol.registry/official": {"status": "active"}
                },
            }
        ]
    }
    servidor = registro_mcp.interpretar(payload)[0]
    assert servidor.transporte == "local"
    assert servidor.paquete == ""


def test_un_local_de_formato_desconocido_no_es_lanzable():
    """`mcpb` y `oci` piden descargar un binario o levantar Docker."""
    payload = {
        "servers": [
            {
                "server": {
                    "name": "x/y",
                    "title": "Y",
                    "description": "",
                    "version": "1",
                    "packages": [{"registryType": "mcpb", "identifier": "https://x/y.mcpb"}],
                },
                "_meta": {
                    "io.modelcontextprotocol.registry/official": {"status": "active"}
                },
            }
        ]
    }
    assert registro_mcp.interpretar(payload)[0].paquete == ""


def test_el_paquete_se_traduce_a_como_se_arranca():
    assert registro_mcp.comando_de_paquete("npm:steam-games-mcp@1.2.0") == (
        "npx",
        ["-y", "steam-games-mcp@1.2.0"],
    )
    assert registro_mcp.comando_de_paquete("pypi:steam-mcp@0.3.0") == (
        "uvx",
        ["steam-mcp==0.3.0"],
    )
    assert registro_mcp.comando_de_paquete("") is None
    assert registro_mcp.comando_de_paquete("oci:algo") is None


def test_verificar_un_local_lanzable_comprueba_que_el_paquete_existe():
    """Sin instalarlo: se le pregunta a npm o PyPI, que es solo leer."""
    servidor = registro_mcp.interpretar(LOCAL_NPM)[0]
    vale, motivo = registro_mcp.verificar(servidor, sonda=lambda s: True)
    assert vale, motivo


def test_verificar_rechaza_un_local_sin_forma_de_lanzarlo():
    servidor = registro_mcp.Servidor(
        nombre="x/y", titulo="Y", descripcion="", version="1", web="",
        transporte="local", activo=True, endpoint="", paquete="",
    )
    vale, motivo = registro_mcp.verificar(servidor, sonda=lambda s: True)
    assert not vale
    assert "instal" in motivo.lower() or "lanzar" in motivo.lower()

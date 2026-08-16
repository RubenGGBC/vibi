"""Forzar que Playwright se enganche al navegador, y no dejarlo para luego.

`browser_mcp` deja el servidor escuchando y `navegador_real` deja el navegador
en pie con las pestañas despiertas. Faltaba una cosa entre medias, y es la que
rompía todo lo demás: **Playwright no se conecta al navegador al arrancar el
servidor, sino en la primera llamada a una herramienta**, que puede ser una
hora más tarde.

Entre las dos cosas, Opera descarta las pestañas que no estás mirando. Y su
`connectOverCDP` espera a que se inicialicen *todas* antes de darse por
conectado —`_waitForAllPagesToBeInitialized`, sin opción de saltárselo—, así
que una sola pestaña descartada tumba la conexión entera a los 30 s. Como una
conexión fallida no se guarda en ninguna parte, la llamada siguiente vuelve a
intentarlo desde cero: **el modelo paga los 30 s en cada herramienta que use**,
y el turno se va a minuto y medio.

Medido en este equipo el 16/08/2026, con el navegador abierto hacía 79 minutos
y 12 pestañas: 6 estaban descartadas, `browser_snapshot` tardaba 30 031 ms y
devolvía `TimeoutError`; tras despertarlas, 633 ms y bien.

Lo que hace este módulo es cerrar ese hueco: llamar nosotros a una herramienta,
en el momento en que sabemos que las pestañas están despiertas, para que la
conexión quede hecha. Comprobado que después sobrevive: una sesión MCP nueva,
abierta tras cerrar del todo la anterior, reaprovecha el navegador en 1,5 s en
vez de reconectar.
"""
from __future__ import annotations

import http.client
import json
import time

# El camino del transporte HTTP con streaming, el mismo que se le declara a
# `agy`. Ver `playwright_mcp_path` en la configuración del servidor.
RUTA = "/mcp"

# Con qué se fuerza la conexión. Tiene que ser algo que obligue a mirar el
# navegador: un `tools/list` lo contesta el servidor él solo, sin engancharse a
# nada, y entonces no serviría para esto. Listar pestañas es lo más barato de
# lo que sí lo obliga, y no toca nada de lo que el usuario tenga delante.
HERRAMIENTA = "browser_tabs"
ARGUMENTOS = {"action": "list"}

# Cuánto puede durar el enganche **entero**, no cada petición. Que sea el total
# importa: son cuatro viajes —abrir, confirmar, llamar y cerrar— y con un margen
# por viaje el peor caso se multiplicaba por cuatro y se salía de los 45 s que
# el servidor espera por una orden de nodo.
#
# Va por encima del margen que se le da a Playwright para engancharse
# (`browser_mcp.CDP_TIMEOUT_MS`) a propósito: si nos rindiéramos antes que él,
# daríamos por fallida una conexión que seguía haciéndose, y el reintento
# abriría una segunda por encima.
TIMEOUT = 9.0

# Lo mínimo que se le deja a una petición aunque el reloj esté acabado. Cortar a
# cero convertiría el último viaje en un error de socket que se leería como
# «el navegador no contesta», que es una cosa muy distinta.
MINIMO_POR_PETICION = 0.5

VERSION_PROTOCOLO = "2025-06-18"


def _conexion(puerto: int, timeout: float):
    """La conexión HTTP, aparte para poder sustituirla en las pruebas."""
    return http.client.HTTPConnection("127.0.0.1", puerto, timeout=timeout)


def _cabeceras(puerto: int, host_declarado: str, sesion: str) -> dict:
    """Las de siempre, más el `Host` con el que el servidor nos reconoce.

    Esto no es cosmético. `--allowed-hosts` **no añade** nombres a los que
    Playwright admite por defecto: los sustituye. Comprobado contra el servidor
    real, que con el mismo puerto contesta 403 a `Host: 127.0.0.1:8931` y deja
    pasar `Host: host.docker.internal:8931`. Como el servidor se levanta
    declarando el nombre que usa el contenedor, el agente tiene que llamarse a
    sí mismo por ese nombre aunque esté hablando con su propia máquina.
    """
    cabeceras = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    nombre = (host_declarado or "").split(",")[0].strip()
    if nombre:
        cabeceras["Host"] = f"{nombre.rsplit(':', 1)[0] if ':' in nombre else nombre}:{puerto}"
    if sesion:
        cabeceras["Mcp-Session-Id"] = sesion
    return cabeceras


def _cuerpo_json(crudo: str) -> dict:
    """El JSON-RPC que viene dentro, sea SSE o una respuesta pelada."""
    for linea in crudo.splitlines():
        if linea.startswith("data:"):
            try:
                return json.loads(linea[5:].strip())
            except ValueError:
                continue
    try:
        return json.loads(crudo)
    except ValueError:
        return {}


def _texto(respuesta: dict) -> str:
    contenido = (respuesta.get("result") or {}).get("content") or []
    return "".join(
        bloque.get("text", "") for bloque in contenido if isinstance(bloque, dict)
    )


def enganchar(puerto: int, host_declarado: str = "", timeout: float = TIMEOUT) -> dict:
    """Deja hecha la conexión al navegador y dice si se pudo.

    Nunca levanta: esto corre en mitad de abrir una sesión, y un fallo aquí no
    es motivo para dejar a Vibi sin navegar. Se devuelve lo que ha pasado para
    que quien llame decida —despertar pestañas y reintentar— y para que quede
    escrito en el log, que es lo que faltaba para ver este problema desde
    fuera: hasta ahora fallaba en silencio y solo se notaba en la lentitud.

    De la respuesta no se lee nada más que si fue buena. Lo que devuelve la
    herramienta son las pestañas del usuario, con sus títulos y sus
    direcciones, y aquí solo se preguntaba si el navegador contesta.
    """
    empezado = time.perf_counter()
    limite = empezado + timeout
    sesion = ""

    def pedir(metodo: str, payload: dict | None) -> tuple[int, dict]:
        nonlocal sesion
        # El margen es lo que quede del total, no el total otra vez: si no, los
        # cuatro viajes podrían costar cuatro veces `timeout`.
        conexion = _conexion(
            puerto, max(MINIMO_POR_PETICION, limite - time.perf_counter())
        )
        try:
            conexion.request(
                metodo,
                RUTA,
                json.dumps(payload) if payload is not None else None,
                _cabeceras(puerto, host_declarado, sesion),
            )
            respuesta = conexion.getresponse()
            crudo = respuesta.read().decode("utf-8", "replace")
            nueva = respuesta.getheader("Mcp-Session-Id")
            if nueva:
                sesion = nueva
            return respuesta.status, _cuerpo_json(crudo)
        finally:
            conexion.close()

    def transcurrido() -> int:
        return int((time.perf_counter() - empezado) * 1000)

    try:
        estado, _ = pedir(
            "POST",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": VERSION_PROTOCOLO,
                    "capabilities": {},
                    "clientInfo": {"name": "vibi-node", "version": "1"},
                },
            },
        )
        if estado >= 400:
            # El 403 es el caso con nombre: el servidor en pie es uno viejo,
            # levantado sin declarar el nombre por el que le estamos llamando.
            return {
                "enganchado": False,
                "ms": transcurrido(),
                "error": f"el servidor MCP contestó {estado} al abrir la sesión",
            }

        pedir("POST", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        estado, respuesta = pedir(
            "POST",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": HERRAMIENTA, "arguments": dict(ARGUMENTOS)},
            },
        )
    except (OSError, http.client.HTTPException, ValueError) as error:
        return {"enganchado": False, "ms": transcurrido(), "error": str(error)}
    finally:
        if sesion:
            # Se abrió solo para esto. Sin cerrarla se acumularían una por
            # sesión de `agy`, y el navegador no se cierra por hacerlo: en modo
            # CDP no es de Playwright, que solo está enganchado a él.
            try:
                pedir("DELETE", None)
            except (OSError, http.client.HTTPException):
                pass

    texto = _texto(respuesta)
    fallo = respuesta.get("error") or {}
    malo = bool(fallo) or (respuesta.get("result") or {}).get("isError")
    if estado >= 400 or malo or texto.lstrip().startswith("### Error"):
        # El fallo de verdad viene con un 200 y el error dentro: el servidor MCP
        # contesta bien a una llamada que salió mal. Solo se guarda la primera
        # línea; el resto es el registro de la conexión CDP y no cabe en un log.
        motivo = (
            fallo.get("message")
            or next((l for l in texto.splitlines() if l.strip() and not l.startswith("#")), "")
            or f"la herramienta {HERRAMIENTA} no contestó"
        )
        return {"enganchado": False, "ms": transcurrido(), "error": motivo.strip()[:200]}

    return {"enganchado": True, "ms": transcurrido(), "error": ""}

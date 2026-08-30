"""El catálogo público de servidores MCP.

Descubrir capacidades ya es un servicio resuelto —el registro oficial expone
una API REST, y MCPfinder agrega además Glama y Smithery—, así que aquí no se
reimplementa nada: se consume. Lo que Vibi aporta está una capa más arriba,
en decidir **qué de todo esto encaja con quien pregunta**.

**El transporte no es un detalle, es la frontera de seguridad.** Un servidor
`remoto` no ejecuta nada en esta máquina pero se lleva los datos fuera; uno
`local` no manda nada fuera pero corre código de un tercero aquí dentro. Son
dos riesgos distintos y el usuario tiene que poder verlos separados antes de
aprobar.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("vibi.registro_mcp")

URL_REGISTRO = "https://registry.modelcontextprotocol.io/v0/servers"

# Cuánto se espera al registro. Es una consulta de conveniencia dentro de una
# entrevista: si tarda más que esto, se sigue sin propuesta antes que dejar al
# usuario mirando una pantalla parada.
ESPERA = 10.0

CLAVE_META = "io.modelcontextprotocol.registry/official"


@dataclass(frozen=True)
class Servidor:
    nombre: str
    titulo: str
    descripcion: str
    version: str
    web: str
    transporte: str
    activo: bool
    endpoint: str = ""


def interpretar(payload: object) -> list[Servidor]:
    """Del JSON del registro a lo que aquí se usa, tolerando que cambie.

    El registro versiona su esquema y se actualiza sin avisarnos. Un campo que
    falte no puede tumbar una entrevista, así que todo se lee a la defensiva y
    lo que no se entiende se descarta en silencio.
    """
    if not isinstance(payload, dict):
        return []
    entradas = payload.get("servers")
    if not isinstance(entradas, list):
        return []

    servidores: list[Servidor] = []
    for entrada in entradas:
        if not isinstance(entrada, dict):
            continue
        bruto = entrada.get("server")
        if not isinstance(bruto, dict) or not bruto.get("name"):
            continue

        remotos = bruto.get("remotes")
        if isinstance(remotos, list):
            transporte = "remoto"
            endpoint = next(
                (
                    str(remoto.get("url") or "").strip()
                    for remoto in remotos
                    if isinstance(remoto, dict)
                    and str(remoto.get("url") or "").startswith(("http://", "https://"))
                ),
                "",
            )
            if not endpoint:
                continue
        elif bruto.get("packages"):
            transporte = "local"
            endpoint = ""
        else:
            # Sin transporte no hay forma de arrancarlo ni de llamarlo, así
            # que proponerlo sería proponer un nombre.
            continue

        meta = entrada.get("_meta") or {}
        oficial = meta.get(CLAVE_META)
        # Defensivo contra cambios de esquema: si oficial no es dict, trata como sin estado.
        if not isinstance(oficial, dict):
            oficial = {}
        servidores.append(
            Servidor(
                nombre=str(bruto["name"]),
                titulo=str(bruto.get("title") or bruto["name"]),
                descripcion=str(bruto.get("description") or ""),
                version=str(bruto.get("version") or ""),
                web=str(bruto.get("websiteUrl") or ""),
                transporte=transporte,
                activo=oficial.get("status") == "active",
                endpoint=endpoint,
            )
        )
    return servidores


def buscar(termino: str, limite: int = 10, cliente: httpx.Client | None = None) -> list[Servidor]:
    """Lo que el registro tenga para ese término, o nada si no contesta.

    Si se inyecta un cliente (para tests), se usa; si no, se usa httpx.get directo.
    Cualquier fallo —HTTP, JSON, cambio de esquema— devuelve lista vacía, no excepción.
    """
    try:
        if cliente is None:
            respuesta = httpx.get(
                URL_REGISTRO,
                params={"search": termino, "limit": limite},
                timeout=ESPERA,
            )
        else:
            respuesta = cliente.get(
                URL_REGISTRO,
                params={"search": termino, "limit": limite},
                timeout=ESPERA,
            )
        respuesta.raise_for_status()
        payload = respuesta.json()
    except Exception as error:  # noqa: BLE001 - cualquier fallo es «sin propuesta»
        log.warning("El registro MCP no contestó a «%s»: %s", termino, error)
        return []
    return [s for s in interpretar(payload) if s.activo]


def _sonda_por_defecto(servidor: Servidor) -> bool:
    """Comprobar que existe algo al otro lado, sin instalarlo.

    Los paquetes locales no se proponen todavía: comprobarlos exige descargar
    y ejecutar código, que ya sería instalar antes de obtener aprobación.
    """
    if servidor.transporte != "remoto":
        return False
    if not servidor.endpoint:
        return False
    try:
        respuesta = httpx.post(
            servidor.endpoint,
            json={
                "jsonrpc": "2.0",
                "id": "vibi-verificacion",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "vibi", "version": "1"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
            timeout=ESPERA,
            follow_redirects=True,
        )
        content_type = respuesta.headers.get("content-type", "").lower()
        return (
            200 <= respuesta.status_code < 300
            and ("application/json" in content_type or "text/event-stream" in content_type)
        )
    except Exception:  # noqa: BLE001
        return False


def verificar(servidor: Servidor, sonda=None) -> tuple[bool, str]:
    """¿Se le puede proponer esto al usuario? Y si no, por qué no."""
    if not servidor.activo:
        return False, "no está activo en el registro oficial"
    if servidor.transporte == "local" and sonda is None:
        return False, "requiere instalación local, todavía no disponible"
    comprobar = sonda or _sonda_por_defecto
    try:
        if not comprobar(servidor):
            return False, "no responde"
    except Exception as error:  # noqa: BLE001
        log.warning("La sonda de %s falló: %s", servidor.nombre, error)
        return False, "no responde"
    return True, ""

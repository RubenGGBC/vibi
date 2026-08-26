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

        if bruto.get("remotes"):
            transporte = "remoto"
        elif bruto.get("packages"):
            transporte = "local"
        else:
            # Sin transporte no hay forma de arrancarlo ni de llamarlo, así
            # que proponerlo sería proponer un nombre.
            continue

        meta = entrada.get("_meta") or {}
        oficial = meta.get(CLAVE_META) or {}
        servidores.append(
            Servidor(
                nombre=str(bruto["name"]),
                titulo=str(bruto.get("title") or bruto["name"]),
                descripcion=str(bruto.get("description") or ""),
                version=str(bruto.get("version") or ""),
                web=str(bruto.get("websiteUrl") or ""),
                transporte=transporte,
                activo=oficial.get("status") == "active",
            )
        )
    return servidores


def buscar(termino: str, limite: int = 10) -> list[Servidor]:
    """Lo que el registro tenga para ese término, o nada si no contesta."""
    try:
        respuesta = httpx.get(
            URL_REGISTRO,
            params={"search": termino, "limit": limite},
            timeout=ESPERA,
        )
        respuesta.raise_for_status()
    except Exception as error:  # noqa: BLE001 - cualquier fallo es «sin propuesta»
        log.warning("El registro MCP no contestó a «%s»: %s", termino, error)
        return []
    return [s for s in interpretar(respuesta.json()) if s.activo]

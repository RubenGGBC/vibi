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
import re
from dataclasses import dataclass

import httpx

log = logging.getLogger("vibi.registro_mcp")

URL_REGISTRO = "https://registry.modelcontextprotocol.io/v0/servers"

# Cuánto se espera al registro. Es una consulta de conveniencia dentro de una
# entrevista: si tarda más que esto, se sigue sin propuesta antes que dejar al
# usuario mirando una pantalla parada.
ESPERA = 10.0

CLAVE_META = "io.modelcontextprotocol.registry/official"


# Cómo se arranca cada clase de paquete. Solo estas dos: `npx` y `uvx` bajan y
# ejecutan sin dejar nada instalado a medias, y son las que cubren 33 de los 39
# paquetes que publica el registro. `mcpb` es un binario suelto que habría que
# descargar y `oci` pide Docker: los dos son otra conversación.
LANZADORES = {
    "npm": ("npx", "-y", "{id}@{version}"),
    "pypi": ("uvx", "{id}=={version}"),
}

# Dónde preguntar si un paquete existe de verdad, sin bajarlo.
INDICES = {
    "npm": "https://registry.npmjs.org/{id}",
    "pypi": "https://pypi.org/pypi/{id}/json",
}


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
    # Cómo se lanza uno local, en la forma «npm:paquete@version». Vacío
    # significa que no sabemos lanzarlo —formato que no cubrimos, o pide una
    # credencial que aquí no tenemos— y entonces no se propone.
    paquete: str = ""


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
        paquete = ""
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
            paquete = _paquete_lanzable(bruto["packages"])
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
                paquete=paquete,
            )
        )
    return servidores


def _paquete_lanzable(paquetes: object) -> str:
    """El primer paquete que sabemos arrancar sin pedirle nada al usuario.

    Se descartan dos cosas distintas y por motivos distintos: los formatos que
    no cubrimos (`mcpb`, `oci`), y los que declaran una variable de entorno
    obligatoria. Estos últimos suelen ser una clave de API —`SPOTIFY_CLIENT_ID`,
    `DISCORD_BOT_TOKEN`—, y declarar el servidor sin ella deja a `agy`
    arrancando algo que va a fallar en cuanto lo llame. Medido el 30/08/2026,
    son 35 de 77 locales: hasta que haya dónde escribir esa clave, fuera.
    """
    if not isinstance(paquetes, list):
        return ""
    for paquete in paquetes:
        if not isinstance(paquete, dict):
            continue
        tipo = str(paquete.get("registryType") or "")
        identificador = str(paquete.get("identifier") or "").strip()
        version = str(paquete.get("version") or "").strip()
        if tipo not in LANZADORES or not identificador or not version:
            continue
        variables = paquete.get("environmentVariables") or []
        if isinstance(variables, list) and any(
            isinstance(v, dict) and v.get("isRequired") for v in variables
        ):
            continue
        return f"{tipo}:{identificador}@{version}"
    return ""


def comando_de_paquete(paquete: str) -> tuple[str, list[str]] | None:
    """Con qué orden se arranca este paquete, o `None` si no sabemos.

    Devuelve la forma que `agy` espera en `command` y `args`, la misma con la
    que se declara el puente de Vibi.
    """
    tipo, _, resto = str(paquete or "").partition(":")
    identificador, _, version = resto.rpartition("@")
    if tipo not in LANZADORES or not identificador or not version:
        return None
    orden = LANZADORES[tipo]
    partes = [
        trozo.format(id=identificador, version=version) for trozo in orden[1:]
    ]
    return orden[0], partes


def _palabras(texto: str) -> set[str]:
    """Las palabras de un texto, en minúsculas y sin separadores."""
    return {p for p in re.split(r"[^0-9a-z]+", str(texto).casefold()) if p}


def relevancia(servidor: Servidor, termino: str) -> float:
    """Cuánto tiene que ver este servidor con lo que se buscaba, de 0 a 3.

    Hace falta porque el registro no ordena por relevancia: busca la cadena
    por todo el documento y devuelve lo que casa, incluido el nombre de quien
    publica. Buscando «gaming» eso colaba `KunaniGaming/agentic-prompt`, que
    son prompts de bolsa. La regla es dónde aparece el término: en el nombre
    del servidor cuenta como que va de eso; en el título o la descripción,
    como que lo menciona; solo en el publicador, como nada.

    Por palabra completa y no por subcadena, la misma trampa que ya se
    corrigió en las recetas del observador: si no, «word» casaría con
    «wordpress».
    """
    buscado = _palabras(termino)
    if not buscado:
        return 0.0

    # El nombre viene como «publicador/servidor»; solo la segunda mitad
    # describe qué hace la cosa.
    _, _, propio = servidor.nombre.rpartition("/")

    puntos = 0.0
    if buscado & _palabras(propio):
        puntos += 2.0
    if buscado & _palabras(servidor.titulo):
        puntos += 1.0
    if buscado & _palabras(servidor.descripcion):
        puntos += 0.5
    return puntos


def buscar(termino: str, limite: int = 10, cliente: httpx.Client | None = None) -> list[Servidor]:
    """Lo que el registro tenga para ese término, o nada si no contesta.

    Si se inyecta un cliente (para tests), se usa; si no, se usa httpx.get directo.
    Cualquier fallo —HTTP, JSON, cambio de esquema— devuelve lista vacía, no excepción.
    """
    # `version=latest` no es un detalle de eficiencia: el registro guarda una
    # entrada por cada versión publicada y sin este filtro el límite se gasta
    # en repetir el mismo servidor. Medido el 30/08/2026 contra el registro
    # real, `search=email` devolvía 20 entradas que eran 6 servidores —siete
    # de ellas idénticas—; con el filtro, 20 servidores distintos.
    params = {"search": termino, "limit": limite, "version": "latest"}
    try:
        if cliente is None:
            respuesta = httpx.get(URL_REGISTRO, params=params, timeout=ESPERA)
        else:
            respuesta = cliente.get(URL_REGISTRO, params=params, timeout=ESPERA)
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


def _sonda_de_paquete(servidor: Servidor) -> bool:
    """¿Existe de verdad el paquete? Se pregunta al índice, no se instala.

    Es la única comprobación honesta que se puede hacer de un local sin
    ejecutar código de un tercero: bajarlo para probarlo ya sería instalarlo
    antes de que nadie lo haya aprobado.
    """
    tipo, _, resto = servidor.paquete.partition(":")
    identificador, _, _version = resto.rpartition("@")
    plantilla = INDICES.get(tipo)
    if not plantilla or not identificador:
        return False
    try:
        respuesta = httpx.get(
            plantilla.format(id=identificador), timeout=ESPERA, follow_redirects=True
        )
        return 200 <= respuesta.status_code < 300
    except Exception:  # noqa: BLE001
        return False


def verificar(servidor: Servidor, sonda=None) -> tuple[bool, str]:
    """¿Se le puede proponer esto al usuario? Y si no, por qué no."""
    if not servidor.activo:
        return False, "no está activo en el registro oficial"
    if servidor.transporte == "local" and not servidor.paquete:
        # Ni formato que sepamos arrancar, ni forma de darle su credencial.
        return False, "no hay forma de lanzarlo sin instalarlo a mano"
    comprobar = sonda or (
        _sonda_de_paquete if servidor.transporte == "local" else _sonda_por_defecto
    )
    try:
        if not comprobar(servidor):
            return False, "no responde"
    except Exception as error:  # noqa: BLE001
        log.warning("La sonda de %s falló: %s", servidor.nombre, error)
        return False, "no responde"
    return True, ""

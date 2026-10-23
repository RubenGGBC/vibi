"""Modelos de Sketchfab: lo que no está en los kits de Kenney.

Kenney cubre lo cotidiano en estilo juguete; Sketchfab tiene más de un millón
de modelos descargables hechos por personas, muchos realistas y escaneados.
Solo se aceptan los que se pueden enseñar y citar sin pedir permiso: CC0 y
CC BY. La procedencia lleva título, autor, licencia y enlace, que es lo que
pide CC BY.

- **Buscar** es anónimo. Se filtra antes de que el agente elija: descargable,
  licencia aceptada, un .glb que no pese demasiado y una geometría razonable
  para el navegador.
- **Importar** pide `SKETCHFAB_TOKEN` (gratis, en sketchfab.com). Se descarga
  el .glb, se mide y se buscan sus partes con nombre, como en la biblioteca, y
  queda guardado: la segunda vez no hay red.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import struct
import tempfile
from pathlib import Path
from typing import NamedTuple

import httpx

from ..config import settings
from . import biblioteca

API = "https://api.sketchfab.com/v3"
TIMEOUT_BUSQUEDA = 8.0
TIMEOUT_DESCARGA = 90.0
LICENCIAS = {"cc0": "CC0", "by": "CC BY 4.0"}
MAX_CARAS = 300_000
UID = re.compile(r"^[0-9a-f]{32}$")
# Lo que el navegador no sabe abrir sin decodificadores que no cargamos.
EXTENSIONES_NO = ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_texture_basisu")
# Nombres de nodo que ponen los exportadores, no las personas.
NOMBRE_AUTOMATICO = re.compile(
    r"^(Object_\d+|RootNode|Root|root|Scene|Sketchfab_model|Sketchfab_Scene|GLTF_SceneRootNode"
    r"|.*\.(fbx|obj|blend|3ds|dae|max|stl|ply|gltf|glb)|_?rootJoint|Armature|defaultMaterial)$",
    re.IGNORECASE,
)
MAX_PARTES = 40


class _Respuesta(NamedTuple):
    estado: int
    contenido: bytes

    def json(self):
        return json.loads(self.contenido)


async def _pedir(
    cliente: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    maximo: int | None = None,
) -> _Respuesta:
    """Un GET. Si el cortafuegos de Sketchfab (AWS WAF) lo desafía, se repite con curl.

    El WAF reconoce la huella TLS de OpenSSL de Python y le pide resolver un
    reto de navegador (202 vacío); la de curl la deja pasar. Así que la
    petición se intenta primero normal y, solo si llega el reto, por curl.
    """
    respuesta = await cliente.get(url, params=params, headers=headers)
    if respuesta.headers.get("x-amzn-waf-action") != "challenge":
        if maximo and len(respuesta.content) > maximo:
            raise biblioteca.BibliotecaError("El modelo pesa demasiado")
        return _Respuesta(respuesta.status_code, respuesta.content)
    return await _con_curl(str(httpx.URL(url, params=params)), headers or {}, maximo, cliente.timeout.read)


async def _con_curl(url: str, headers: dict, maximo: int | None, espera: float | None) -> _Respuesta:
    curl = shutil.which("curl")
    if curl is None:
        raise biblioteca.BibliotecaError(
            "Sketchfab bloquea a este servidor (pide un navegador) y no hay curl para esquivarlo"
        )
    with tempfile.TemporaryDirectory() as carpeta:
        cuerpo = Path(carpeta) / "cuerpo"
        # Las cabeceras (el token) van en un archivo propio y no en la línea
        # de órdenes: ahí las vería cualquiera con `ps`.
        cabeceras = Path(carpeta) / "cabeceras"
        cabeceras.write_text("".join(f"{k}: {v}\n" for k, v in headers.items()), encoding="utf-8")
        os.chmod(cabeceras, 0o600)
        orden = [
            curl, "-sS", "-L", "--max-time", str(int(espera or TIMEOUT_DESCARGA)),
            "-H", f"@{cabeceras}", "-o", str(cuerpo), "-w", "%{http_code}",
        ]
        if maximo:
            orden += ["--max-filesize", str(maximo)]
        proceso = await asyncio.create_subprocess_exec(
            *orden, url, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        salida, error = await proceso.communicate()
        if proceso.returncode == 63:
            raise biblioteca.BibliotecaError("El modelo pesa demasiado")
        if proceso.returncode != 0:
            raise httpx.TransportError(error.decode(errors="replace")[:200])
        contenido = cuerpo.read_bytes() if cuerpo.exists() else b""
        return _Respuesta(int(salida.decode() or 0), contenido)


def disponible() -> bool:
    return bool(settings.sketchfab_token)


def _consulta_en_ingles(consulta: str) -> str:
    palabras = [biblioteca.SINONIMOS.get(p, p).split()[0] for p in biblioteca._palabras(consulta)]
    return " ".join(palabras)


def _resultado(modelo: dict) -> dict | None:
    licencia = (modelo.get("license") or {}).get("label", "")
    slug = next(
        (s for s, nombre in (("cc0", "CC0"), ("by", "CC Attribution")) if licencia.startswith(nombre)),
        None,
    )
    glb = (modelo.get("archives") or {}).get("glb") or {}
    megas = (glb.get("size") or 0) / 1e6
    if (
        slug is None
        or licencia.startswith("CC Attribution-")  # NC, ND, SA: no
        or not modelo.get("isDownloadable")
        or not glb
        or megas > settings.estudio_sketchfab_max_mb
        or (modelo.get("faceCount") or 0) > MAX_CARAS
    ):
        return None
    return {
        "id": f"sketchfab/{modelo['uid']}",
        "titulo": modelo.get("name", "")[:80],
        "autor": (modelo.get("user") or {}).get("displayName", "")[:60],
        "licencia": LICENCIAS[slug],
        "caras": modelo.get("faceCount"),
        "megas": round(megas, 1),
        "animado": bool(modelo.get("animationCount")),
    }


async def buscar(consulta: str, limite: int = 8) -> list[dict]:
    """Los mejores descargables de la consulta, ya filtrados. Sin red: error."""
    texto = _consulta_en_ingles(consulta)
    if not texto:
        return []
    parametros = {"type": "models", "q": texto, "downloadable": "true", "count": 24}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_BUSQUEDA, follow_redirects=True) as cliente:
            respuestas = await asyncio.gather(
                *(_pedir(cliente, f"{API}/search", params={**parametros, "license": s}) for s in LICENCIAS)
            )
        if any(r.estado != 200 for r in respuestas):
            raise ValueError(f"estado {[r.estado for r in respuestas]}")
        listas = [r.json().get("results", []) for r in respuestas]
    except (httpx.HTTPError, ValueError) as error:
        raise biblioteca.BibliotecaError(
            f"Sketchfab no responde ({error.__class__.__name__})"
        ) from error
    vistos: set[str] = set()
    encontrados = []
    # Se alternan las dos licencias: la búsqueda de cada una ya viene ordenada
    # por relevancia, y así ninguna tapa a la otra.
    for fila in range(max((len(lista) for lista in listas), default=0)):
        for lista in listas:
            if fila < len(lista):
                resultado = _resultado(lista[fila])
                if resultado and resultado["id"] not in vistos:
                    vistos.add(resultado["id"])
                    encontrados.append(resultado)
    # Primero los que se llaman como lo pedido: la relevancia de Sketchfab
    # también mira etiquetas y da «rifle» para «telescopio» (por la mira).
    pedidas = set(biblioteca._palabras(consulta)) | set(biblioteca._palabras(texto))
    encontrados.sort(key=lambda e: not pedidas & set(biblioteca._palabras(e["titulo"])))
    return encontrados[:limite]


def _partes_con_nombre(glb: bytes, candidatas: list[str]) -> list[str]:
    """De los nodos con nombre, los que una persona nombró y tienen geometría."""
    gltf, _ = biblioteca._leer_glb(glb)
    nodos = gltf.get("nodes", [])

    def con_malla(i: int, vistos: set[int]) -> bool:
        if i in vistos:
            return False
        vistos.add(i)
        nodo = nodos[i]
        return "mesh" in nodo or any(con_malla(h, vistos) for h in nodo.get("children", []))

    utiles = {n.get("name") for i, n in enumerate(nodos) if n.get("name") and con_malla(i, set())}
    partes = [p for p in candidatas if p in utiles and not NOMBRE_AUTOMATICO.match(p)]
    # Muchas partes con nombre suelen ser una malla troceada al exportar: no
    # sirven para señalar nada.
    return partes if len(partes) <= MAX_PARTES else []


_candados: dict[str, asyncio.Lock] = {}


async def importar(uid: str) -> dict:
    """Descarga el modelo, lo mide y lo deja en la biblioteca como uno más."""
    if not UID.match(uid):
        raise biblioteca.BibliotecaError(f"«{uid}» no es un id de Sketchfab")
    if not disponible():
        raise biblioteca.BibliotecaError(
            "Este servidor no tiene SKETCHFAB_TOKEN: los modelos de Sketchfab no se "
            "pueden descargar. Usa uno de Kenney o compón con formas"
        )
    candado = _candados.setdefault(uid, asyncio.Lock())
    async with candado:
        modelo_id = f"sketchfab/{uid}"
        existente = biblioteca.ficha(modelo_id)
        if existente and biblioteca.ruta(modelo_id):
            return existente
        cabecera = {"Authorization": f"Token {settings.sketchfab_token}"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_DESCARGA, follow_redirects=True) as cliente:
                info = await _pedir(cliente, f"{API}/models/{uid}")
                if info.estado == 404:
                    raise biblioteca.BibliotecaError(f"Sketchfab no tiene el modelo {uid}")
                if info.estado != 200:
                    raise httpx.HTTPError(f"estado {info.estado}")
                datos = info.json()
                slug = (datos.get("license") or {}).get("slug")
                if slug not in LICENCIAS:
                    raise biblioteca.BibliotecaError(
                        f"La licencia de «{datos.get('name')}» ({slug}) no permite usarlo aquí: "
                        "solo CC0 y CC BY"
                    )
                enlace = await _pedir(cliente, f"{API}/models/{uid}/download", headers=cabecera)
                if enlace.estado in (401, 403):
                    raise biblioteca.BibliotecaError(
                        "Sketchfab rechaza el token (SKETCHFAB_TOKEN): revísalo en el servidor"
                    )
                if enlace.estado != 200:
                    raise httpx.HTTPError(f"estado {enlace.estado}")
                glb_info = enlace.json().get("glb")
                if not glb_info:
                    raise biblioteca.BibliotecaError(f"«{datos.get('name')}» no se ofrece en .glb")
                maximo = settings.estudio_sketchfab_max_mb * 1_000_000
                if (glb_info.get("size") or 0) > maximo:
                    raise biblioteca.BibliotecaError(
                        f"«{datos.get('name')}» pesa {glb_info['size'] / 1e6:.0f} MB: busca uno más ligero"
                    )
                archivo = await _pedir(cliente, glb_info["url"], maximo=maximo)
                if archivo.estado != 200:
                    raise httpx.HTTPError(f"estado {archivo.estado}")
        except httpx.HTTPError as error:
            raise biblioteca.BibliotecaError(
                f"No se pudo descargar de Sketchfab ({error.__class__.__name__}): sin red "
                "solo están los modelos ya importados"
            ) from error
        glb = archivo.contenido
        try:
            gltf, _ = biblioteca._leer_glb(glb)
        except (ValueError, struct.error) as error:
            raise biblioteca.BibliotecaError("El archivo de Sketchfab no es un .glb válido") from error
        requeridas = set(gltf.get("extensionsRequired", [])) & set(EXTENSIONES_NO)
        if requeridas:
            raise biblioteca.BibliotecaError(
                f"«{datos.get('name')}» usa compresión que el visor no abre ({', '.join(requeridas)})"
            )
        ficha = biblioteca.describir("sketchfab", uid, glb)
        if not all(m > 0 for m in ficha["medidas"]):
            raise biblioteca.BibliotecaError(f"«{datos.get('name')}» no tiene geometría medible")
        ficha.update(
            {
                "partes": _partes_con_nombre(glb, ficha["partes"]),
                "titulo": datos.get("name", "")[:80],
                "autor": (datos.get("user") or {}).get("displayName", "")[:60],
                "licencia": LICENCIAS[slug],
                "pagina": datos.get("viewerUrl"),
            }
        )
        return await asyncio.to_thread(biblioteca.registrar_externo, ficha, glb)

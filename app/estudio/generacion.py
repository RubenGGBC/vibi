"""Modelos 3D generados con IA, para lo que no está en ninguna biblioteca.

El último recurso: primero Kenney, luego Sketchfab y, si nadie ha hecho ese
objeto, se genera a partir de una descripción con Hunyuan3D en fal.ai. Sale
una forma creíble, no una verificada: un «motor de cuatro tiempos» generado
parece un motor, pero sus piezas no tienen por qué ser las de verdad. Por eso
lleva procedencia de Vibi (lo redactado) y no de catálogo.

- Cada descripción se genera **una sola vez**: el resultado se guarda en la
  biblioteca como un modelo importado más, y pedirla otra vez no cuesta nada.
- Tarda de medio minuto a dos. La herramienta espera un rato; si no llega,
  la generación sigue en segundo plano y la siguiente llamada la recoge.
- Hay un tope de generaciones por usuario y día: cada una cuesta dinero.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time

import httpx

from ..config import settings
from . import biblioteca

COLA = "https://queue.fal.run"
TIMEOUT_HTTP = 30.0
TIMEOUT_TOTAL = 300.0
INTERVALO = 3.0
MAX_MB = 40
EXTENSIONES_NO = ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_texture_basisu")


class GeneracionPendiente(Exception):
    """Sigue generándose: hay que volver a pedirlo en un rato."""


def disponible() -> bool:
    return bool(settings.fal_key)


def id_de(descripcion: str) -> str:
    """El mismo texto (sin mayúsculas ni espacios de más) da el mismo modelo."""
    normal = " ".join(descripcion.casefold().split())
    resumen = hashlib.sha256(normal.encode("utf-8")).hexdigest()[:12]
    lema = re.sub(r"[^a-z0-9]+", "-", normal)[:40].strip("-") or "objeto"
    return f"generado/{lema}-{resumen}"


_tareas: dict[str, asyncio.Task] = {}
_cuentas: dict[tuple[str, str], int] = {}


def _contar(user_id: str) -> None:
    dia = time.strftime("%Y-%m-%d")
    clave = (user_id, dia)
    if _cuentas.get(clave, 0) >= settings.estudio_generaciones_por_dia:
        raise biblioteca.BibliotecaError(
            f"Ya se han generado {settings.estudio_generaciones_por_dia} modelos hoy: el tope "
            "es para no gastar de más. Usa la biblioteca o compón con formas"
        )
    _cuentas[clave] = _cuentas.get(clave, 0) + 1


async def _generar(modelo_id: str, descripcion: str) -> dict:
    cabecera = {"Authorization": f"Key {settings.fal_key}"}
    entrada = {
        "prompt": descripcion[:1000],
        "enable_pbr": True,
        # Lo justo para el navegador: el mínimo de Hunyuan3D son 40.000 caras.
        "face_count": 60_000,
        "generate_type": "Normal",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_HTTP, follow_redirects=True) as cliente:
            envio = await cliente.post(
                f"{COLA}/{settings.estudio_generacion_modelo}", json=entrada, headers=cabecera
            )
            if envio.status_code in (401, 403):
                raise biblioteca.BibliotecaError("fal.ai rechaza la clave (FAL_KEY): revísala en el servidor")
            envio.raise_for_status()
            pedido = envio.json()
            limite = time.monotonic() + TIMEOUT_TOTAL
            while True:
                estado = await cliente.get(pedido["status_url"], headers=cabecera)
                estado.raise_for_status()
                if estado.json().get("status") == "COMPLETED":
                    break
                if time.monotonic() > limite:
                    raise biblioteca.BibliotecaError("La generación tardó demasiado y se abandonó")
                await asyncio.sleep(INTERVALO)
            resultado = await cliente.get(pedido["response_url"], headers=cabecera)
            if resultado.status_code == 422:
                raise biblioteca.BibliotecaError(
                    f"fal.ai no genera esa descripción: {resultado.text[:200]}"
                )
            resultado.raise_for_status()
            datos = resultado.json()
            archivo = (datos.get("model_glb") or (datos.get("model_urls") or {}).get("glb") or {})
            if not archivo.get("url"):
                raise biblioteca.BibliotecaError("fal.ai no devolvió ningún .glb")
            if (archivo.get("file_size") or 0) > MAX_MB * 1_000_000:
                raise biblioteca.BibliotecaError("El modelo generado pesa demasiado")
            descarga = await cliente.get(archivo["url"], timeout=120.0)
            descarga.raise_for_status()
    except httpx.HTTPError as error:
        raise biblioteca.BibliotecaError(
            f"No se pudo generar el modelo ({error.__class__.__name__}): sin red no hay generación"
        ) from error
    glb = descarga.content
    if len(glb) > MAX_MB * 1_000_000:
        raise biblioteca.BibliotecaError("El modelo generado pesa demasiado")
    gltf, _ = biblioteca._leer_glb(glb)
    if set(gltf.get("extensionsRequired", [])) & set(EXTENSIONES_NO):
        raise biblioteca.BibliotecaError("El modelo generado usa una compresión que el visor no abre")
    kit, nombre = modelo_id.split("/", 1)
    ficha = biblioteca.describir(kit, nombre, glb)
    if not all(m > 0 for m in ficha["medidas"]):
        raise biblioteca.BibliotecaError("El modelo generado no tiene geometría")
    ficha.update({
        # Una malla generada es una sola pieza: sus nodos no significan nada.
        "partes": [],
        "titulo": descripcion[:80],
        "autor": f"IA ({settings.estudio_generacion_modelo.split('/')[1]})",
        "plataforma": "fal.ai",
        "licencia": "generado",
        "generado": True,
    })
    return await asyncio.to_thread(biblioteca.registrar_externo, ficha, glb)


async def obtener(user_id: str, descripcion: str, espera: float = 90.0) -> dict:
    """La ficha del modelo de esa descripción: guardada, en marcha o nueva.

    Si no llega en `espera` segundos lanza `GeneracionPendiente` y la
    generación sigue sola; la siguiente llamada la recoge.
    """
    modelo_id = id_de(descripcion)
    guardada = biblioteca.ficha(modelo_id)
    if guardada and biblioteca.ruta(modelo_id):
        return guardada
    tarea = _tareas.get(modelo_id)
    if tarea is None or (tarea.done() and tarea.exception() is not None):
        if not disponible():
            raise biblioteca.BibliotecaError(
                "Este servidor no tiene FAL_KEY: no se pueden generar modelos. "
                "Usa la biblioteca o compón con formas"
            )
        _contar(user_id)
        tarea = asyncio.create_task(_generar(modelo_id, descripcion))
        _tareas[modelo_id] = tarea
    try:
        return await asyncio.wait_for(asyncio.shield(tarea), timeout=espera)
    except TimeoutError as error:
        raise GeneracionPendiente(modelo_id) from error

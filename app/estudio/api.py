"""Lo que pide la sección Estudio de la PWA."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import auth
from . import atlas, biblioteca, capturas, escena as esc, modelos

router = APIRouter(prefix="/api/estudio", tags=["estudio"])


@router.get("/escena")
def ver_escena(user: dict = Depends(auth.current_user)) -> dict:
    return esc.cargar(user["id"])


class PasoActual(BaseModel):
    indice: int = Field(ge=0)


@router.post("/paso")
async def cambiar_paso(
    cuerpo: PasoActual, user: dict = Depends(auth.current_user)
) -> dict:
    """El alumno pasa de paso: todas sus ventanas le siguen."""
    try:
        await esc.cambiar_paso(user["id"], cuerpo.indice)
    except esc.EscenaError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"indice": cuerpo.indice}


class Respuesta(BaseModel):
    indice: int = Field(ge=0)
    opcion: int = Field(ge=0)


@router.post("/respuesta")
async def responder(cuerpo: Respuesta, user: dict = Depends(auth.current_user)) -> dict:
    """El alumno contesta la pregunta de un paso. El tutor lo ve después."""
    try:
        return await esc.responder(user["id"], cuerpo.indice, cuerpo.opcion)
    except esc.EscenaError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class AjusteManual(BaseModel):
    parte: str | None = Field(default=None, max_length=120)
    posicion: list[float] | None = None
    rotacion: list[float] | None = None
    escala: list[float] | None = None
    restablecer: bool = False


@router.post("/objetos/{objeto_id}/ajuste")
async def ajustar_objeto(
    objeto_id: str, cuerpo: AjusteManual, user: dict = Depends(auth.current_user)
) -> dict:
    """El alumno ha movido, girado o escalado algo con el gizmo."""
    # Perezoso y por `tools`: es quien carga las herramientas de Estudio en
    # orden; `composicion` a secas entra en el ciclo primitivas ↔ tools.
    from .. import tools  # noqa: F401, PLC0415
    from . import composicion  # noqa: PLC0415

    try:
        return await composicion.ajustar_a_mano(
            user["id"], objeto_id, **cuerpo.model_dump()
        )
    except esc.EscenaError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/capturas/{captura_id}")
async def subir_captura(
    captura_id: str, request: Request, user: dict = Depends(auth.current_user)
) -> dict:
    cuerpo = await request.body()
    if not cuerpo or len(cuerpo) > capturas.MAX_BYTES:
        raise HTTPException(status_code=413, detail="Captura vacía o demasiado grande")
    if not cuerpo.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=415, detail="La captura tiene que ser JPEG")
    try:
        capturas.depositar(captura_id, user["id"], cuerpo)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"ok": True}


@router.get("/modelos")
def listar_modelos(user: dict = Depends(auth.current_user)) -> list[dict]:
    return [modelos.publico(m) for m in modelos.catalogo()]


@router.get("/modelos/{modelo_id}/archivo")
def archivo_modelo(modelo_id: str, user: dict = Depends(auth.current_user)):
    ruta = modelos.ruta_archivo(modelo_id)
    if ruta is None:
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    tipo = "model/gltf+json" if ruta.suffix.lower() == ".gltf" else "model/gltf-binary"
    return FileResponse(ruta, media_type=tipo)


@router.get("/atlas/{clave}/archivo")
def archivo_atlas(clave: str, user: dict = Depends(auth.current_user)):
    ruta = atlas.ruta_cache(clave)
    if ruta is None:
        raise HTTPException(status_code=404, detail="Modelo del atlas no encontrado")
    return FileResponse(ruta, media_type="model/gltf-binary")


@router.get("/biblioteca/{kit}/{nombre}")
async def archivo_biblioteca(kit: str, nombre: str, user: dict = Depends(auth.current_user)):
    modelo_id = f"{kit}/{nombre}"
    if biblioteca.ficha(modelo_id) is None:
        raise HTTPException(status_code=404, detail="Ese objeto no está en la biblioteca")
    try:
        ruta = await biblioteca.asegurar(modelo_id)
    except biblioteca.BibliotecaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return FileResponse(ruta, media_type="model/gltf-binary")

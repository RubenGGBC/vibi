"""Lo que pide la sección Estudio de la PWA."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import auth
from . import capturas, escena as esc, modelos

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

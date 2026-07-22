"""Servicio del build de React con fallback para rutas de la SPA."""
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if path in {"api", "salud"} or path.startswith(("api/", "salud/")):
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)

        if response.status_code == 404 and not Path(path).suffix:
            return await super().get_response("index.html", scope)
        return response


def mount_pwa(app: FastAPI, directory: str | Path) -> bool:
    build = Path(directory).expanduser().resolve()
    if not (build / "index.html").is_file():
        return False
    app.mount("/", SPAStaticFiles(directory=build, html=True), name="pwa")
    return True

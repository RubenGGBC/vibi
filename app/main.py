"""Punto de entrada de Morgana.

Arranca tres cosas en el mismo proceso:
  - la API HTTP y la PWA React servida por FastAPI
  - el worker de la cola de tareas agénticas
  - el bot de Telegram (polling)

Ejecutar:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, db, events, nodes, tasks, transfers
from .api import api_router, auth_router, voice_router
from .channels import telegram
from .config import settings
from .executors import antigravity_chat, chat
from .web import mount_pwa

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("morgana")

# Las URLs de Telegram contienen el token del bot. Evitamos que httpx
# las escriba completas en el log en cada petición.
logging.getLogger("httpx").setLevel(logging.WARNING)


# Lo que se espera a que vuelva algún nodo antes de precalentar. Sus agentes
# reconectan solos, pero tardan en enterarse de que el servidor ha vuelto, y lo
# que se decida al montar la sesión dura lo que dure el proceso de `agy`: si el
# ordenador del usuario todavía no está, esa sesión se queda sin navegador
# hasta que caduque, quince minutos después. Se espera de verdad, y no un rato
# fijo, porque un margen a ojo falla justo en el caso peor —servidor y agente
# reiniciados a la vez— que es el más habitual al desplegar.
#
# Nadie está esperando esto: el precalentado va en segundo plano. Y cuando no
# hay ningún nodo el tope se paga una sola vez, al arrancar, no por turno.
ESPERA_NODOS_SEGUNDOS = 90.0
SONDEO_NODOS = 1.0


async def _esperar_algun_nodo() -> bool:
    limite = asyncio.get_running_loop().time() + ESPERA_NODOS_SEGUNDOS
    while asyncio.get_running_loop().time() < limite:
        if nodes.manager.online_ids():
            return True
        await asyncio.sleep(SONDEO_NODOS)
    return False


async def _precalentar_antigravity() -> None:
    """Deja lista una sesión de `agy` para quien tenga ese motor elegido."""
    if not await _esperar_algun_nodo():
        log.info("Ningún dispositivo conectado: precaliento sin navegador")
    for user in db.list_users_with_chat_provider("antigravity"):
        await antigravity_chat.warm_up(user["id"], user["nombre"])


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    if (
        len(settings.jwt_secret) < 32
        or settings.jwt_secret == "cambia-esto-por-un-secreto-largo"
    ):
        raise RuntimeError(
            "JWT_SECRET debe tener al menos 32 caracteres y no ser el ejemplo"
        )
    db.init_db()
    await tasks.reencolar_pendientes()
    worker = asyncio.create_task(tasks.worker())
    caducador = asyncio.create_task(nodes.expiry_worker())
    caducador_envios = asyncio.create_task(transfers.expiry_worker())

    bot = None
    if settings.telegram_bot_token:
        bot = telegram.crear_bot()
        await bot.initialize()
        await bot.start()
        await bot.updater.start_polling()
        log.info("Bot de Telegram escuchando")
    else:
        log.warning("TELEGRAM_BOT_TOKEN vacío: arranco sin bot (solo API)")

    precalentado = None
    if settings.antigravity_warm_up:
        # Abrir `agy` cuesta ~10 s. Se pagan aquí, en segundo plano, para que
        # el primer mensaje del usuario no los espere.
        precalentado = asyncio.create_task(_precalentar_antigravity())

    yield

    if precalentado:
        precalentado.cancel()
    await chat.close_all_sessions()
    worker.cancel()
    caducador.cancel()
    caducador_envios.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker
    with contextlib.suppress(asyncio.CancelledError):
        await caducador
    with contextlib.suppress(asyncio.CancelledError):
        await caducador_envios
    await tasks.detener_ejecuciones()
    if bot:
        await bot.updater.stop()
        await bot.stop()
        await bot.shutdown()


def create_app(
    start_background: bool = True,
    frontend_dir: str | Path | None = None,
) -> FastAPI:
    web_app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan if start_background else None,
    )
    web_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://tauri.localhost", "http://localhost:1420"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    web_app.include_router(auth_router)
    web_app.include_router(voice_router)
    web_app.include_router(api_router)
    web_app.include_router(events.router)
    web_app.include_router(nodes.router)
    web_app.include_router(transfers.router)
    nodes.registrar_observador_ordenes(transfers.orden_completada)
    tasks.registrar_notificador(events.notificar)
    tasks.registrar_observador_tareas(events.tarea_actualizada)

    @web_app.exception_handler(StarletteHTTPException)
    async def api_http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": str(exc.detail)},
                headers=exc.headers,
            )
        return await http_exception_handler(request, exc)

    @web_app.exception_handler(RequestValidationError)
    async def api_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=422, content={"error": "Parámetros inválidos"}
            )
        return await request_validation_exception_handler(request, exc)

    @web_app.get("/salud")
    async def salud():
        return {"estado": "viva", "app": settings.app_name}

    @web_app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; "
            "font-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self' ws: wss:; "
            # El audio de /api/tts se reproduce desde un blob: creado con
            # URL.createObjectURL. Sin esto cae a default-src 'self', que no
            # cubre el esquema, y la voz se va al fallback del navegador.
            "media-src 'self' blob:; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    async def api_no_encontrada(_: dict = Depends(auth.current_user)):
        raise HTTPException(status_code=404, detail="Endpoint API no encontrado")

    for path in ("/api", "/api/{path:path}"):
        web_app.add_api_route(
            path,
            api_no_encontrada,
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            include_in_schema=False,
        )

    static_dir = frontend_dir if frontend_dir is not None else settings.frontend_dist
    if not mount_pwa(web_app, static_dir):
        log.info("Build de la PWA no encontrado en %s", static_dir)

    return web_app


app = create_app()

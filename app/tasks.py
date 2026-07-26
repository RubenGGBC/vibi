"""Orquestador de tareas agénticas de Morgana.

Una cola asyncio procesa la planificación de una en una y mantiene
registradas las ejecuciones aprobadas para poder cerrarlas limpiamente.
El ciclo de vida de una tarea:

  pendiente -> planificando -> esperando_aprobacion
     -> (aprueba) ejecutando -> completada
     -> (rechaza) rechazada

Las notificaciones al usuario (plan listo, resultado, errores) salen
por un callback que registra el canal (Telegram hoy; la PWA mañana usará
el mismo mecanismo). El core no sabe qué es Telegram: solo "notifica".
"""
import asyncio
from dataclasses import dataclass
from difflib import get_close_matches
import logging
from pathlib import Path
from typing import Awaitable, Callable, Literal

from . import db
from .claude_models import ClaudeModel, DEFAULT_CLAUDE_MODEL
from .config import settings

log = logging.getLogger("morgana.tasks")

# Callback de notificación: (user_id, texto, task_id | None, mostrar_acciones)
Notificador = Callable[[str, str, str | None, bool], Awaitable[None]]
# Callback de cambio: (user_id, tarea_completa)
ObservadorTarea = Callable[[str, dict], Awaitable[None]]
# Callback de actividad: (user_id) -> muestra que el agente sigue trabajando
IndicadorActividad = Callable[[str], Awaitable[None]]

_cola: asyncio.Queue[str] = asyncio.Queue()
_notificadores: list[Notificador] = []
_observadores_tareas: list[ObservadorTarea] = []
_indicador: IndicadorActividad | None = None
_ejecuciones: dict[str, asyncio.Task[None]] = {}

# Telegram expira el "escribiendo..." a los ~5s; lo refrescamos antes.
INTERVALO_INDICADOR = 4.0


EstadoResolucion = Literal[
    "ok", "sin_proyectos", "requiere_proyecto", "no_encontrado"
]


@dataclass(frozen=True)
class ResolucionProyecto:
    estado: EstadoResolucion
    workspace: str | None = None
    proyectos: tuple[str, ...] = ()
    sugerencias: tuple[str, ...] = ()


def directorio_usuario(user_id: str) -> Path:
    """Devuelve WORKSPACE_ROOT/<user_id> sin permitir escapes de ruta."""
    raiz = Path(settings.workspace_root).expanduser().resolve()
    usuario = (raiz / user_id).resolve()
    if usuario.parent != raiz:
        raise ValueError("El directorio del usuario queda fuera de WORKSPACE_ROOT")
    usuario.mkdir(parents=True, exist_ok=True)
    return usuario


def validar_workspace_usuario(user_id: str, workspace: str | Path) -> str:
    """Valida que workspace sea un subdirectorio directo y existente del usuario."""
    base = directorio_usuario(user_id)
    resuelto = Path(workspace).expanduser().resolve()
    if resuelto.parent != base or not resuelto.is_dir():
        raise ValueError("El proyecto no es un subdirectorio válido del usuario")
    return str(resuelto)


def listar_proyectos(user_id: str) -> list[str]:
    """Lista solo subdirectorios cuyo realpath permanece dentro del usuario."""
    base = directorio_usuario(user_id)
    proyectos: list[str] = []
    for entrada in base.iterdir():
        try:
            if (
                entrada.is_dir()
                and entrada.resolve().parent == base
                and not entrada.name.startswith(".morgana-clone-")
            ):
                proyectos.append(entrada.name)
        except OSError:
            log.warning("No se pudo inspeccionar el proyecto %s", entrada)
    return sorted(proyectos, key=str.casefold)


def resolver_proyecto(user_id: str, proyecto: str | None) -> ResolucionProyecto:
    """Resuelve un nombre contra los proyectos visibles del usuario."""
    proyectos = listar_proyectos(user_id)
    disponibles = tuple(proyectos)
    if not proyectos:
        return ResolucionProyecto("sin_proyectos")

    if not proyecto or not proyecto.strip():
        if len(proyectos) == 1:
            workspace = validar_workspace_usuario(
                user_id, directorio_usuario(user_id) / proyectos[0]
            )
            return ResolucionProyecto("ok", workspace, disponibles)
        return ResolucionProyecto("requiere_proyecto", proyectos=disponibles)

    buscado = proyecto.strip()

    # El nombre exacto siempre tiene prioridad.
    coincidencia = next((p for p in proyectos if p == buscado), None)
    if coincidencia is None:
        # Permite diferencias de mayúsculas cuando no generan ambigüedad.
        sin_mayusculas = [p for p in proyectos if p.casefold() == buscado.casefold()]
        if len(sin_mayusculas) == 1:
            coincidencia = sin_mayusculas[0]

    if coincidencia is not None:
        workspace = validar_workspace_usuario(
            user_id, directorio_usuario(user_id) / coincidencia
        )
        return ResolucionProyecto("ok", workspace, disponibles)

    mapa = {p.casefold(): p for p in proyectos}
    cercanas = get_close_matches(
        buscado.casefold(), list(mapa), n=3, cutoff=0.35
    )
    sugerencias = tuple(mapa[nombre] for nombre in cercanas)
    return ResolucionProyecto(
        "no_encontrado", proyectos=disponibles, sugerencias=sugerencias
    )


def registrar_notificador(fn: Notificador) -> None:
    if fn not in _notificadores:
        _notificadores.append(fn)


def registrar_observador_tareas(fn: ObservadorTarea) -> None:
    if fn not in _observadores_tareas:
        _observadores_tareas.append(fn)


def registrar_indicador(fn: IndicadorActividad) -> None:
    global _indicador
    _indicador = fn


async def _notificar(
    user_id: str,
    texto: str,
    task_id: str | None = None,
    acciones: bool = False,
) -> None:
    for notifier in tuple(_notificadores):
        try:
            await notifier(user_id, texto, task_id, acciones)
        except Exception:  # noqa: BLE001
            log.exception("Un notificador falló para el usuario %s", user_id)


async def _emitir_tarea(task: dict) -> None:
    for observer in tuple(_observadores_tareas):
        try:
            await observer(task["user_id"], task)
        except Exception:  # noqa: BLE001
            log.exception("Un observador de tareas falló para %s", task["id"])


async def _actualizar_tarea(task_id: str, **campos) -> dict | None:
    db.update_task(task_id, **campos)
    task = db.get_task(task_id)
    if task:
        await _emitir_tarea(task)
    return task


async def _mientras_activo(user_id: str, corutina):
    """Ejecuta corutina mostrando actividad ('escribiendo...') mientras dure,
    para que el usuario vea que el agente sigue pensando/trabajando y no
    que el proceso se ha quedado colgado."""
    if _indicador is None:
        return await corutina

    async def _parpadeo() -> None:
        while True:
            await _indicador(user_id)
            await asyncio.sleep(INTERVALO_INDICADOR)

    tarea_parpadeo = asyncio.create_task(_parpadeo())
    try:
        return await corutina
    finally:
        tarea_parpadeo.cancel()


async def encolar_tarea(
    user_id: str,
    nombre: str,
    prompt: str,
    workspace: str,
    modelo: ClaudeModel = DEFAULT_CLAUDE_MODEL,
) -> dict:
    workspace = validar_workspace_usuario(user_id, workspace)
    task = db.create_task(user_id, prompt, workspace, modelo)
    db.log_event(
        "tarea_creada", user_id, task_id=task["id"], prompt=prompt,
        workspace=workspace,
    )
    await _emitir_tarea(task)
    await _cola.put(task["id"])
    return task


async def aprobar_tarea(task_id: str) -> bool:
    """Llamado por el canal cuando el usuario pulsa Aprobar."""
    task = db.get_task(task_id)
    if not task or not db.transition_task(
        task_id, "esperando_aprobacion", "ejecutando"
    ):
        return False
    task = db.get_task(task_id)
    if task:
        await _emitir_tarea(task)
    db.log_event("tarea_aprobada", task["user_id"], task_id=task_id)
    _iniciar_ejecucion(task_id)
    return True


async def rechazar_tarea(task_id: str) -> bool:
    task = db.get_task(task_id)
    if not task or not db.transition_task(
        task_id, "esperando_aprobacion", "rechazada"
    ):
        return False
    task = db.get_task(task_id)
    if task:
        await _emitir_tarea(task)
    db.log_event("tarea_rechazada", task["user_id"], task_id=task_id)
    await _notificar(
        task["user_id"],
        "Tarea descartada. Aquí estaré si cambias de idea.",
        task_id,
        False,
    )
    return True


def _iniciar_ejecucion(task_id: str) -> None:
    """Registra la ejecución para poder cancelarla durante el apagado."""
    job = asyncio.create_task(_ejecutar(task_id), name=f"morgana-ejecutar-{task_id}")
    _ejecuciones[task_id] = job

    def _retirar(finalizada: asyncio.Task[None]) -> None:
        if _ejecuciones.get(task_id) is finalizada:
            _ejecuciones.pop(task_id, None)
        if not finalizada.cancelled():
            error = finalizada.exception()
            if error:
                log.error("La ejecución %s terminó sin gestionar: %s", task_id, error)

    job.add_done_callback(_retirar)


async def _ejecutar(task_id: str) -> None:
    from .executors import claude_agent

    task = db.get_task(task_id)
    user = db.get_user_by_id(task["user_id"])
    nombre = user["nombre"] if user else "usuario"
    try:
        workspace = validar_workspace_usuario(task["user_id"], task["workspace"])
        resultado = await _mientras_activo(
            task["user_id"],
            claude_agent.ejecutar(
                task["user_id"],
                nombre,
                workspace,
                task["prompt"],
                task["plan"] or "",
                task.get("modelo", DEFAULT_CLAUDE_MODEL),
            ),
        )
        await _actualizar_tarea(task_id, estado="completada", resultado=resultado)
        db.log_event("tarea_completada", task["user_id"], task_id=task_id)
        await _notificar(
            task["user_id"], f"✅ Tarea completada:\n\n{resultado}", task_id
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Error ejecutando tarea %s", task_id)
        await _actualizar_tarea(task_id, estado="error", resultado=str(e))
        await _notificar(task["user_id"], f"❌ La tarea falló: {e}", task_id)


async def reencolar_pendientes() -> None:
    """Al arrancar, recupera tareas que se quedaron a medias porque la cola
    solo vive en memoria (fase 1). 'esperando_aprobacion' no necesita esto:
    el plan ya está en la BD y el botón de Telegram lleva el task_id."""
    pendientes = db.get_tasks_by_estado("pendiente", "planificando")
    for task in pendientes:
        await _cola.put(task["id"])
    if pendientes:
        log.info("Reencoladas %d tareas tras el reinicio", len(pendientes))

    interrumpidas = db.get_tasks_by_estado("ejecutando")
    for task in interrumpidas:
        await _actualizar_tarea(
            task["id"],
            estado="error",
            resultado="Ejecución interrumpida por un reinicio del servicio.",
        )
        db.log_event(
            "tarea_interrumpida", task["user_id"], task_id=task["id"],
            motivo="reinicio",
        )
    if interrumpidas:
        log.warning(
            "Marcadas como interrumpidas %d ejecuciones de un proceso anterior",
            len(interrumpidas),
        )


async def detener_ejecuciones() -> None:
    """Cancela ejecuciones vivas y evita dejar estados atascados al apagar."""
    activas = tuple(_ejecuciones.items())
    for _, job in activas:
        job.cancel()
    if activas:
        await asyncio.gather(*(job for _, job in activas), return_exceptions=True)

    for task_id, _ in activas:
        task = db.get_task(task_id)
        if not task or task["estado"] != "ejecutando":
            continue
        mensaje = "Ejecución interrumpida por el apagado del servicio."
        await _actualizar_tarea(task_id, estado="error", resultado=mensaje)
        db.log_event(
            "tarea_interrumpida", task["user_id"], task_id=task_id,
            motivo="apagado",
        )
        await _notificar(task["user_id"], f"⚠️ {mensaje}", task_id)


async def worker() -> None:
    """Bucle del worker: coge tareas de la cola y genera su plan."""
    from .executors import claude_agent

    log.info("Worker de tareas arrancado")
    while True:
        task_id = await _cola.get()
        task = db.get_task(task_id)
        if not task:
            continue
        await _actualizar_tarea(task_id, estado="planificando")
        await _notificar(
            task["user_id"],
            "🔮 Recibido. Estoy analizando el workspace y preparando un plan...",
            task_id,
        )
        try:
            user = db.get_user_by_id(task["user_id"])
            nombre = user["nombre"] if user else "usuario"
            workspace = validar_workspace_usuario(task["user_id"], task["workspace"])
            plan = await _mientras_activo(
                task["user_id"],
                claude_agent.planificar(
                    task["user_id"],
                    nombre,
                    workspace,
                    task["prompt"],
                    task.get("modelo", DEFAULT_CLAUDE_MODEL),
                ),
            )
            await _actualizar_tarea(
                task_id, estado="esperando_aprobacion", plan=plan
            )
            db.log_event("plan_generado", task["user_id"], task_id=task_id)
            await _notificar(
                task["user_id"],
                f"📋 Plan listo:\n\n{plan}\n\n¿Lo aplico?",
                task_id,
                True,  # el canal añade los botones Aprobar/Rechazar
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Error planificando tarea %s", task_id)
            await _actualizar_tarea(task_id, estado="error", resultado=str(e))
            await _notificar(
                task["user_id"], f"❌ No pude generar el plan: {e}", task_id
            )

"""Canal Telegram de Morgana — el primer cliente.

Responsabilidades del canal (y solo estas):
  - vincular el chat de Telegram con un usuario de Morgana
  - pasar mensajes al core (router -> vía rápida o agéntica)
  - renderizar notificaciones, incluido el plan con botones
    Aprobar / Rechazar (el flujo de aprobación humana)

El canal NO contiene lógica de negocio: la PWA de fase 2 hará
exactamente estas mismas llamadas contra el core.
"""
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .. import db, files, taint, tasks
from ..config import settings
from ..core import messages as message_core

log = logging.getLogger("morgana.telegram")

_app: Application | None = None

# Telegram corta mensajes >4096 chars; troceamos con margen
MAX_MSG = 3900

# Límites de la API de Telegram, no nuestros: un bot no puede enviar archivos de
# más de 50 MB ni descargar los de más de 20 MB. Se avisa cuando se topan, para
# que no parezca un fallo de Morgana.
MAX_DOCUMENTO_BYTES = 50 * 1024 * 1024
MAX_DESCARGA_BYTES = 20 * 1024 * 1024
PROMPT_PENDIENTE_PROYECTO = "prompt_pendiente_proyecto"


def _trocear(texto: str) -> list[str]:
    return [texto[i:i + MAX_MSG] for i in range(0, len(texto), MAX_MSG)] or [""]


async def notificar(
    user_id: str,
    texto: str,
    task_id: str | None = None,
    acciones: bool = False,
) -> None:
    """Callback que el orquestador usa para hablar con el usuario."""
    user = db.get_user_by_id(user_id)
    if not (user and user["telegram_chat_id"] and _app):
        return
    chat_id = user["telegram_chat_id"]
    if task_id and settings.pwa_base_url:
        base_url = settings.pwa_base_url.rstrip("/")
        texto = f"{texto}\n\n🔗 {base_url}/tareas/{task_id}"
    trozos = _trocear(texto)
    for trozo in trozos[:-1]:
        await _app.bot.send_message(chat_id=chat_id, text=trozo)
    teclado = None
    if task_id and acciones:
        teclado = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Aprobar", callback_data=f"aprobar:{task_id}"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"rechazar:{task_id}"),
        ]])
    await _app.bot.send_message(chat_id=chat_id, text=trozos[-1], reply_markup=teclado)


async def enviar_archivo(user_id: str, file: dict) -> bool:
    """Entrega al móvil un archivo que Morgana ya tiene.

    Telegram no deja a un bot mandar más de 50 MB. Por encima de eso se dice por
    qué y dónde está el archivo: si no, parecería un fallo nuestro.
    """
    user = db.get_user_by_id(user_id)
    if not (user and user["telegram_chat_id"] and _app):
        return False
    chat_id = user["telegram_chat_id"]

    if file["size_bytes"] > MAX_DOCUMENTO_BYTES:
        # No vale con pegar aquí el enlace de descarga: ese endpoint pide el
        # JWT en la cabecera y un toque desde Telegram no lo lleva. Se manda a
        # la pantalla de archivos, donde la sesión ya está iniciada.
        aviso = (
            f"«{file['name']}» pesa más de lo que Telegram deja mandar a un bot "
            "(50 MB), así que lo tienes en tus archivos de Morgana."
        )
        if settings.pwa_base_url:
            aviso += f"\n\n🔗 {settings.pwa_base_url.rstrip('/')}/archivos"
        await _app.bot.send_message(chat_id=chat_id, text=aviso)
        return True

    ruta = files.path_for_file(file, user_id)
    if ruta is None or not ruta.is_file():
        return False
    with ruta.open("rb") as contenido:
        await _app.bot.send_document(
            chat_id=chat_id, document=contenido, filename=file["name"]
        )
    return True


async def documento(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Guarda lo que mandes al bot como archivo tuyo, sin adivinar destinos.

    Queda esperando instrucciones: «mándalo al PC» o «resúmelo» ya encuentran el
    archivo dentro de Morgana.
    """
    chat_id = update.effective_chat.id
    user = db.user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("Primero preséntate con /start 🙂")
        return

    adjunto = update.message.document
    if adjunto is None and update.message.photo:
        # De una foto llegan varias resoluciones; la última es la mayor.
        adjunto = update.message.photo[-1]
    if adjunto is None:
        return

    nombre = getattr(adjunto, "file_name", None) or (
        f"foto-{adjunto.file_unique_id}.jpg"
    )
    if (adjunto.file_size or 0) > MAX_DESCARGA_BYTES:
        await update.message.reply_text(
            f"«{nombre}» pesa más de 20 MB y la API de Telegram no me deja "
            "descargarlo. Súbelo desde Morgana en el navegador y lo tendré "
            "igual."
        )
        return

    await update.message.reply_chat_action(ChatAction.UPLOAD_DOCUMENT)
    try:
        descargado = await adjunto.get_file()
        contenido = bytes(await descargado.download_as_bytearray())
    except Exception:  # noqa: BLE001 - un fallo de red no debe tumbar el bot
        log.exception("No se pudo descargar el adjunto de Telegram")
        await update.message.reply_text(
            "No he podido recoger ese archivo de Telegram. Prueba otra vez."
        )
        return

    async def _trozos():
        yield contenido

    try:
        stored = await files.store_stream(
            user["id"],
            nombre,
            _trozos(),
            content_type=getattr(adjunto, "mime_type", None),
        )
    except files.FileServiceError as error:
        await update.message.reply_text(f"No he podido guardarlo: {error}")
        return

    db.upsert_device(f"telegram:{chat_id}", user["id"], "telegram", "Telegram")
    db.log_event(
        "archivo_recibido_telegram",
        user["id"],
        file_id=stored["id"],
        bytes=stored["size_bytes"],
    )
    # El contenido lo has traído tú, pero no lo has escrito: lo que hay dentro
    # puede venir de cualquier parte.
    taint.registro.marcar(user["id"], "telegram.document")
    await update.message.reply_text(
        f"Guardado como «{stored['name']}». Dime qué hago con él: puedo "
        "mandarlo a otro dispositivo o mirarlo."
    )


async def indicar_actividad(user_id: str) -> None:
    """Callback que el orquestador usa para mostrar 'escribiendo...' mientras
    el agente sigue pensando o trabajando."""
    user = db.get_user_by_id(user_id)
    if not (user and user["telegram_chat_id"] and _app):
        return
    await _app.bot.send_chat_action(chat_id=user["telegram_chat_id"], action=ChatAction.TYPING)


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if settings.telegram_owner_chat_id and chat_id != settings.telegram_owner_chat_id:
        await update.message.reply_text("Este es un asistente privado. 🔒")
        return
    if not settings.telegram_owner_chat_id:
        owner = db.first_telegram_user()
        if owner and owner["telegram_chat_id"] != chat_id:
            await update.message.reply_text("Este es un asistente privado. 🔒")
            return
    nombre = update.effective_user.first_name or "usuario"
    user = db.get_or_create_user(nombre, telegram_chat_id=chat_id)
    db.upsert_device(
        f"telegram:{chat_id}", user["id"], "telegram", "Telegram"
    )
    db.log_event("login_telegram", user["id"], chat_id=chat_id)
    await update.message.reply_text(
        f"Hola, {nombre}. Soy Morgana. 🔮\n\n"
        "Háblame normal para preguntas rápidas, o encárgame trabajo sobre "
        "tu código (\"investiga X en mi proyecto\", \"hazme un plan para Y\") "
        "y te traeré un plan para que lo apruebes antes de tocar nada."
    )


async def cmd_proyectos(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista los proyectos disponibles para el usuario autenticado."""
    user = db.user_by_chat_id(update.effective_chat.id)
    if not user:
        await update.message.reply_text("Primero preséntate con /start 🙂")
        return

    proyectos = tasks.listar_proyectos(user["id"])
    if not proyectos:
        await update.message.reply_text(
            "No tienes proyectos todavía. Crea una carpeta dentro de tu "
            "directorio de usuario en WORKSPACE_ROOT."
        )
        return

    listado = "\n".join(f"• {nombre}" for nombre in proyectos)
    await update.message.reply_text(f"Proyectos disponibles:\n\n{listado}")


async def _renderizar_encargo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    resultado: message_core.ResultadoMensaje,
) -> None:
    resolucion = resultado.resolucion

    if resultado.task:
        context.user_data.pop(PROMPT_PENDIENTE_PROYECTO, None)
        nombre_proyecto = Path(resolucion.workspace).name
        await update.message.reply_text(
            f"Proyecto seleccionado: {nombre_proyecto}. 🛠️ "
            "Lo encolo y te mando el plan."
        )
        return

    if resolucion.estado == "sin_proyectos":
        context.user_data.pop(PROMPT_PENDIENTE_PROYECTO, None)
        await update.message.reply_text(
            "No encuentro ningún proyecto. Crea o clona una carpeta dentro de "
            "tu directorio de usuario en WORKSPACE_ROOT y prueba de nuevo."
        )
        return

    context.user_data[PROMPT_PENDIENTE_PROYECTO] = prompt
    if resolucion.estado == "requiere_proyecto":
        listado = ", ".join(resolucion.proyectos)
        await update.message.reply_text(
            f"Tienes varios proyectos: {listado}.\n\n"
            "¿En cuál quieres que trabaje? Responde con el nombre exacto."
        )
        return

    if resolucion.sugerencias:
        sugerencias = ", ".join(resolucion.sugerencias)
        texto = "No encuentro ese proyecto. " f"¿Querías decir: {sugerencias}?"
    else:
        disponibles = ", ".join(resolucion.proyectos)
        texto = (
            "No encuentro ese proyecto. "
            f"Disponibles: {disponibles}."
        )
    await update.message.reply_text(
        f"{texto}\n\nResponde con el nombre exacto del proyecto."
    )


async def mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = db.user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("Primero preséntate con /start 🙂")
        return
    db.upsert_device(
        f"telegram:{chat_id}", user["id"], "telegram", "Telegram"
    )

    texto = update.message.text
    prompt_pendiente = context.user_data.get(PROMPT_PENDIENTE_PROYECTO)
    if prompt_pendiente:
        db.log_event(
            "seleccion_proyecto", user["id"], proyecto=texto, canal="telegram"
        )
        resultado = await message_core.procesar_encargo(
            user, prompt_pendiente, texto, canal="telegram"
        )
        await _renderizar_encargo(
            update, context, prompt_pendiente, resultado
        )
        return

    resultado = await message_core.procesar_mensaje(
        user, texto, canal="telegram"
    )

    if resultado.via in ("rapida", "herramienta"):
        for trozo in _trocear(resultado.respuesta or ""):
            await update.message.reply_text(trozo)
    else:
        await _renderizar_encargo(update, context, texto, resultado)


async def botones(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    accion, task_id = q.data.split(":", 1)
    user = db.user_by_chat_id(update.effective_chat.id)
    task = db.get_task(task_id)
    if not user or not task or task["user_id"] != user["id"]:
        await q.answer("Esta tarea no te pertenece.", show_alert=True)
        return

    if accion == "aprobar":
        changed = await tasks.aprobar_tarea(task_id)
        if not changed:
            await q.answer("La tarea ya no espera aprobación.", show_alert=True)
            return
        await q.answer()
        await q.edit_message_reply_markup(None)
        await q.message.reply_text("Plan aprobado. Manos a la obra. ⚙️")
    elif accion == "rechazar":
        changed = await tasks.rechazar_tarea(task_id)
        if not changed:
            await q.answer("La tarea ya no espera aprobación.", show_alert=True)
            return
        await q.answer()
        await q.edit_message_reply_markup(None)
    else:
        await q.answer("Acción desconocida.", show_alert=True)


def crear_bot() -> Application:
    global _app
    _app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )
    _app.add_handler(CommandHandler("start", cmd_start))
    _app.add_handler(CommandHandler("proyectos", cmd_proyectos))
    _app.add_handler(CallbackQueryHandler(botones))
    _app.add_handler(
        MessageHandler(filters.Document.ALL | filters.PHOTO, documento)
    )
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje))
    tasks.registrar_notificador(notificar)
    tasks.registrar_indicador(indicar_actividad)
    return _app

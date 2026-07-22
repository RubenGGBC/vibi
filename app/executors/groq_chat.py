"""Vía rápida: chat conversacional persistente con Groq."""
import logging

from groq import AsyncGroq

from .. import db, events
from ..config import settings
from ..core.context_builder import BuiltContext, build_turn_context

log = logging.getLogger("morgana.groq_chat")

_client: AsyncGroq | None = None

PERSONALIDAD = """Eres Morgana, la asistente personal de {nombre}. Vives en su
servidor y le acompañas desde el móvil, el PC y la pantalla del lab.

# Personalidad
- Directa y resolutiva: primero la respuesta, luego el matiz si hace falta.
- Ironía fina y ocasional: una pincelada seca cuando la situación lo pide,
  nunca en cada mensaje, nunca a costa de la claridad. Si dudas entre
  hacer la gracia o ser útil, sé útil.
- Cero servilismo: no digas "¡Claro que sí!", "¡Excelente pregunta!" ni
  pidas perdón por sistema. Trata a {nombre} como a un colega competente.
- Tienes opiniones: si te pregunta cuál opción es mejor, moja. Nada de
  "depende de tus necesidades" sin más.

# Formato (reglas duras)
- PROHIBIDO usar emojis, emoticonos o símbolos decorativos. Tus respuestas
  se leen en voz alta por síntesis de voz y los emojis se pronuncian
  literalmente. Nunca, en ningún canal.
- Respuestas concisas: esto es un chat, no un ensayo. Una a tres frases
  para lo normal; solo te extiendes si te piden detalle.
- Sin listas ni markdown salvo que aporten de verdad (código, pasos).
  Habla en prosa natural, como se habla.
- Responde en el idioma del usuario (normalmente español).

# Lo que no haces tú
Si {nombre} pide algo sobre su código o proyectos que requeriría un
agente trabajando (editar, refactorizar, implementar), dile que lo
reformule como tarea: el router lo enviará al agente.

# Búsqueda web
Cuando la respuesta dependa de información actual (noticias, precios,
versiones, normas, horarios, datos poco conocidos), usa la búsqueda web
si está disponible. No busques para conversación general ni hechos
estables. Si buscas, basa la respuesta en las fuentes y conserva las
citas automáticas.

# Cómo hablas
Escribes para ser escuchada, no leída. Tus respuestas las pronuncia
una voz sintética, así que redacta como se habla en una conversación
real:
- Nada de abreviaturas ni notación escrita: di "frente a" y no "vs",
  "por ejemplo" y no "p. ej.", "etcétera" y no "etc.". Los símbolos
  (/, &, →, %) exprésalos con palabras.
- Los números, dilos como se dicen: "unos treinta euros", "las cinco
  y media", no "30€" ni "17:30".
- Nunca dictes URLs, rutas de archivo ni fragmentos de código. Si hay
  código de por medio, describe la idea y ofrece dejarle el detalle
  en el chat.
- Frases cortas, una idea por frase. Conectores de conversación
  ("mira", "eso sí", "de todas formas"), no de redacción ("no obstante",
  "cabe destacar", "en primer lugar").
- Los nombres técnicos, úsalos con naturalidad y sin apellidos
  innecesarios: mejor "Mongo" que "MongoDB versión seis punto cero"
  si el contexto ya está claro.
- La prueba: si lo que has escrito no lo dirías en voz alta a un
  compañero en el lab, reescríbelo."""

def client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


def _contexto(
    nombre: str,
    historial: list[dict],
    tareas: list[dict],
    mensaje: str,
    rol_instrucciones: str,
) -> BuiltContext:
    return build_turn_context(
        system_prompt=PERSONALIDAD.format(nombre=nombre),
        instruction_role=rol_instrucciones,
        tasks=tareas,
        recent_messages=historial,
        user_message=mensaje,
        task_budget=settings.groq_task_context_tokens,
        recent_budget=settings.groq_recent_context_tokens,
    )


async def responder(
    user_id: str,
    nombre: str,
    mensaje: str,
    origen: str = "pwa",
    client_ref: str | None = None,
) -> str:
    conversation = db.get_or_create_active_conversation(user_id)
    historial = db.list_context_messages(
        conversation["id"], settings.groq_recent_context_tokens
    )
    tareas = db.list_live_tasks(user_id)
    user_message = db.add_conversation_message(
        conversation["id"], "user", mensaje, origen, client_ref
    )
    await events.mensaje_chat(user_id, user_message)

    usa_busqueda = settings.groq_web_search_enabled
    modelo = settings.groq_search_model if usa_busqueda else settings.groq_model
    contexto = _contexto(
        nombre,
        historial,
        tareas,
        mensaje,
        "developer" if usa_busqueda else "system",
    )
    log.debug(
        "Contexto Groq: tareas=%d ventana=%d total=%d tokens aprox",
        contexto.task_tokens,
        contexto.window_tokens,
        contexto.total_tokens,
    )

    try:
        if usa_busqueda:
            # Compound rechaza la combinación de parámetros de sampling del
            # chat normal; su API decide internamente cómo generar y buscar.
            resp = await client().chat.completions.create(
                model=modelo,
                messages=contexto.messages,
            )
        else:
            resp = await client().chat.completions.create(
                model=modelo,
                messages=contexto.messages,
                temperature=0.7,
                max_tokens=1024,
            )
    except Exception as exc:
        if not usa_busqueda:
            raise
        log.warning(
            "Compound (%s) falló, uso %s sin búsqueda: %s",
            modelo, settings.groq_model, exc,
        )
        resp = await client().chat.completions.create(
            model=settings.groq_model,
            messages=_contexto(
                nombre, historial, tareas, mensaje, "system"
            ).messages,
            temperature=0.7,
            max_tokens=1024,
        )
    texto = resp.choices[0].message.content or ""
    assistant_message = db.add_conversation_message(
        conversation["id"], "assistant", texto, origen
    )
    await events.mensaje_chat(user_id, assistant_message)
    return texto

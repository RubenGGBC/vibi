"""Lo que llega de los nodos cuando a alguien le notifican algo.

El camino entero: el nodo ve una notificación de Windows y la manda, aquí se
filtra contra los silencios del usuario, y lo que sobrevive se convierte en una
frase que Vibi dice en voz alta.

**Enunciar no es leer.** «Ana: ¿quedamos mañana a las cinco?» leído tal cual
suena a máquina deletreando un formulario. Lo que se quiere oír es «Ana dice que
si puedes quedar mañana a las cinco»: la misma información dicha por alguien que
te la está contando. Eso lo hace el modelo rápido, con una llamada por aviso que
sobreviva al filtro — que es la razón de que el filtro vaya **antes** y no
después: la promoción de NVIDIA no llega a costar nada.

**Y si el modelo no está, el aviso llega igual.** Con una frase más sosa, pero
llega. Quedarse callado porque Groq esté caído sería peor que sonar a máquina:
lo que no se puede perder es que Ana ha escrito.
"""
from __future__ import annotations

import logging

from . import avisos_silencio, db, events
from .config import settings

log = logging.getLogger("vibi.avisos")

# Lo que se acepta de cada campo. Un nodo comprometido no puede meter una novela
# en el contexto del modelo ni en la base de datos.
MAX_TEXTO = 400

# Lo que puede durar la frase hablada. Una notificación es un aviso, no una
# lectura: si el modelo se enrolla, se corta.
MAX_FRASE = 300

INSTRUCCIONES = (
    "Convierte una notificación del ordenador en una frase corta y hablada, "
    "en español, como se lo contarías a alguien que está a tu lado.\n"
    "- Di quién avisa y qué dice, en una sola frase.\n"
    "- No leas literalmente: «Ana: ¿quedamos mañana?» se cuenta como "
    "«Ana pregunta si quedáis mañana».\n"
    "- No añadas nada que no esté en la notificación.\n"
    "- Nada de emojis, comillas ni preámbulos. Solo la frase."
)


def sanear(crudo: object) -> dict | None:
    """Deja el aviso del nodo en algo de tamaño y forma conocidos.

    Devuelve None si no queda nada que decir: una notificación sin aplicación,
    sin título y sin cuerpo no es un aviso, es ruido del protocolo.
    """
    if not isinstance(crudo, dict):
        return None

    def campo(nombre: str) -> str:
        return " ".join(str(crudo.get(nombre) or "").split())[:MAX_TEXTO]

    limpio = {
        "app": campo("app"),
        "titulo": campo("titulo"),
        "cuerpo": campo("cuerpo"),
    }
    if not limpio["titulo"] and not limpio["cuerpo"]:
        return None
    return limpio


def frase_sosa(aviso: dict) -> str:
    """Lo que se dice cuando el modelo no puede reformular."""
    limpio = sanear(aviso) or {}
    partes = [p for p in (limpio.get("titulo"), limpio.get("cuerpo")) if p]
    cuerpo = ": ".join(partes) if partes else "te ha llegado un aviso"
    app = limpio.get("app")
    return f"{app}: {cuerpo}" if app else cuerpo


async def _pedir_al_modelo(user_id: str, aviso: dict) -> str:
    """La reformulación, por el motor rápido."""
    from groq import AsyncGroq  # noqa: PLC0415 - solo si hay que hablar

    from . import ai_providers  # noqa: PLC0415 - circular con el chat

    resuelto = ai_providers.resolve_lane(user_id, "chat")
    cliente = AsyncGroq(api_key=resuelto.api_key or settings.groq_api_key)
    respuesta = await cliente.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": INSTRUCCIONES},
            {
                "role": "user",
                "content": (
                    f"Aplicación: {aviso['app']}\n"
                    f"Título: {aviso['titulo']}\n"
                    f"Cuerpo: {aviso['cuerpo']}"
                ),
            },
        ],
        max_tokens=120,
    )
    return respuesta.choices[0].message.content or ""


async def enunciar(user_id: str, aviso: dict) -> str:
    """La frase que Vibi va a decir. Nunca vacía y nunca eterna."""
    limpio = sanear(aviso)
    if limpio is None:
        return ""
    try:
        dicho = (await _pedir_al_modelo(user_id, limpio) or "").strip()
    except Exception as error:  # noqa: BLE001 - el aviso importa más que el estilo
        log.warning("No pude enunciar el aviso (%s); lo digo tal cual", error)
        dicho = ""
    return (dicho or frase_sosa(limpio))[:MAX_FRASE]


def _reglas(user_id: str) -> list[avisos_silencio.Regla]:
    return [
        avisos_silencio.Regla(app=fila["app"], patron=fila["patron"])
        for fila in db.list_mute_rules(user_id)
    ]


async def _contar_al_companion(user_id: str, dicho: str) -> None:
    """Se lo manda al companion por el canal que ya existía, marcado para hablar.

    `hablar` va aparte del texto a propósito: el companion ya recibía avisos que
    solo se leen —una tarea terminada, un archivo que llegó— y esos no deben
    ponerse a sonar de repente porque compartan canal.
    """
    await events.notificar_hablando(user_id, dicho)


async def recibir(user_id: str, crudo: object) -> bool:
    """Un aviso recién llegado de un nodo. Devuelve si se ha llegado a decir."""
    limpio = sanear(crudo)
    if limpio is None:
        return False
    if not avisos_silencio.pasa(limpio, _reglas(user_id)):
        return False

    dicho = await enunciar(user_id, limpio)
    if not dicho:
        return False
    await _contar_al_companion(user_id, dicho)
    db.log_event("aviso_dicho", user_id, app=limpio["app"])
    return True


async def callar(user_id: str, app: str = "", patron: str = "") -> dict:
    """Guarda un silencio y devuelve cómo contárselo al usuario.

    El alcance lo elige quien llama —el modelo, interpretando lo que se dijo— y
    aquí solo se guarda y se explica. Decirlo en voz alta es parte del trato: si
    Vibi calla más de la cuenta, hay que poder corregirla en el acto.
    """
    regla = db.add_mute_rule(user_id, app, patron)
    if regla is None:
        return {
            "regla": None,
            "dicho": avisos_silencio.describir(
                avisos_silencio.Regla(app=app, patron=patron)
            )
            if (app or patron)
            else "No he entendido qué querías callar, así que no he callado nada.",
        }
    return {
        "regla": regla,
        "dicho": avisos_silencio.describir(
            avisos_silencio.Regla(app=regla["app"], patron=regla["patron"])
        ),
    }

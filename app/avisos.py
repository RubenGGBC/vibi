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

# Cuántos avisos se guardan mientras el usuario está en stand-by. Se retienen
# en memoria y no en SQLite a propósito: lo retenido solo tiene sentido dentro
# del rato que dura la vigilancia, y un aviso de hace tres reinicios contado
# como si acabara de pasar es peor que no contarlo. Si el servidor se reinicia,
# lo retenido se pierde y la vigilancia sigue, que es el reparto correcto.
MAX_RETENIDOS = 20

# user_id -> lo que se ha callado mientras miraba otra cosa.
_retenidos: dict[str, list[str]] = {}

INSTRUCCIONES_STANDBY = (
    "Alguien te pidió silencio: está esperando otra cosa y no quiere que le "
    "interrumpan. Acaba de llegarle esta notificación.\n"
    "Responde en UNA línea con este formato exacto:\n"
    "GRAVE: <frase>  — no puede esperar; hay que interrumpirle igualmente.\n"
    "ESPERA: <frase> — se le cuenta luego, cuando termine lo que espera.\n"
    "La frase se escribe igual en los dos casos: en español, una sola frase "
    "corta y hablada, contando quién avisa y qué dice. Sin emojis ni comillas.\n"
    "Ante la duda, ESPERA: te pidieron silencio y romperlo sin motivo es "
    "justo lo que hace que la próxima vez no te lo pidan."
)

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


async def _pedir_al_modelo(
    user_id: str, aviso: dict, instrucciones: str = INSTRUCCIONES
) -> str:
    """La reformulación, por el motor rápido.

    `instrucciones` es un parámetro y no una constante porque en stand-by la
    misma llamada tiene que decidir además si esto puede esperar. Se aprovecha
    la que ya se hacía: juzgar la urgencia no cuesta ni una llamada más.
    """
    from groq import AsyncGroq  # noqa: PLC0415 - solo si hay que hablar

    from . import ai_providers  # noqa: PLC0415 - circular con el chat

    resuelto = ai_providers.resolve_lane(user_id, "chat")
    cliente = AsyncGroq(api_key=resuelto.api_key or settings.groq_api_key)
    respuesta = await cliente.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": instrucciones},
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
        **ai_providers.opciones_groq(settings.groq_model),
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


async def enunciar_en_standby(user_id: str, aviso: dict) -> tuple[bool, str]:
    """La frase, y además si esto no puede esperar. Nunca vacía.

    Si el modelo no contesta o contesta cualquier cosa, se asume que **puede
    esperar**. Es lo contrario que en `enunciar`, y a propósito: allí el fallo
    seguro es hablar de más, aquí es interrumpir un silencio que te pidieron.
    """
    limpio = sanear(aviso)
    if limpio is None:
        return False, ""
    try:
        linea = await _pedir_al_modelo(user_id, limpio, INSTRUCCIONES_STANDBY)
    except Exception as error:  # noqa: BLE001 - el aviso importa más que el estilo
        log.warning("No pude juzgar el aviso en stand-by (%s); esperará", error)
        return False, frase_sosa(limpio)

    cabeza, _, resto = (linea or "").strip().partition(":")
    frase = " ".join(resto.split())[:MAX_FRASE] or frase_sosa(limpio)
    return cabeza.strip().upper() == "GRAVE", frase


def retener(user_id: str, frase: str) -> None:
    """Guarda algo que se ha callado, para contarlo cuando termine el silencio."""
    cola = _retenidos.setdefault(user_id, [])
    if len(cola) >= MAX_RETENIDOS:
        # Lleno: se tira lo más viejo. Un stand-by largo con el ordenador
        # hablador no puede acabar en una lista de cuarenta cosas que nadie
        # va a escuchar.
        cola.pop(0)
    cola.append(frase[:MAX_FRASE])


def resumen_retenido(user_id: str) -> str:
    """Lo que se calló mientras miraba, en una frase. Vacía la cola al leerla.

    Se resume en vez de soltar la cola entera porque locutar seis avisos
    seguidos al salir del silencio es peor que no haber callado nunca: el
    usuario pidió no ser interrumpido, no que se le acumulara la interrupción.
    """
    cola = _retenidos.pop(user_id, [])
    if not cola:
        return ""
    if len(cola) == 1:
        return f"Mientras miraba: {cola[0]}"
    cabeza = "; ".join(cola[:3])
    if len(cola) <= 3:
        return f"Mientras miraba te llegaron {len(cola)} cosas: {cabeza}."
    return (
        f"Mientras miraba te llegaron {len(cola)} cosas. Las últimas: "
        f"{cabeza}."
    )


def hay_retenidos(user_id: str) -> int:
    return len(_retenidos.get(user_id, []))


async def recibir(user_id: str, crudo: object) -> bool:
    """Un aviso recién llegado de un nodo. Devuelve si se ha llegado a decir."""
    limpio = sanear(crudo)
    if limpio is None:
        return False
    if not avisos_silencio.pasa(limpio, _reglas(user_id)):
        return False

    # En stand-by el filtro no cambia —los silencios del usuario mandan igual—
    # pero lo que sobrevive ya no se locuta sin más: se juzga si puede esperar.
    from . import vigilancias  # noqa: PLC0415 - circular con el juicio de novedades

    if vigilancias.hay_viva(user_id):
        grave, frase = await enunciar_en_standby(user_id, limpio)
        if not frase:
            return False
        if not grave:
            retener(user_id, frase)
            db.log_event("aviso_retenido", user_id, app=limpio["app"])
            return False
        await _contar_al_companion(user_id, frase)
        db.log_event("aviso_dicho", user_id, app=limpio["app"], grave=True)
        return True

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

"""Si la persona está encima de Vibi ahora mismo, y por dónde.

Existe para una sola decisión: cuándo se le puede dar un turno a agy sin
quitárselo a nadie. Agy lleva **una conversación a la vez**, así que un aviso
que entre mientras el usuario está hablando no compite por el turno: espera.

Se miran las dos superficies por separado porque se comportan distinto:

- **La cara** (el companion flotante) es un estado, no un evento: mientras esté
  despierta —escuchando, pensando, hablando— hay una conversación de voz en
  curso aunque en este instante nadie diga nada. Por eso la reporta el
  frontend y aquí solo se guarda.
- **El hilo de chat** es a ratos: se escribe, se contesta, y se deja. No hay un
  «cerrar el chat» que avise, así que se mide por silencio: si hace
  `CHAT_EN_REPOSO` segundos que no se mueve, se da por libre.

**Un estado que caduca.** Si el companion se cierra de golpe —o se lo lleva un
cuelgue— nadie manda el «ya no estoy». Sin caducidad, la cara se quedaría
eternamente «activa» y los avisos no se contarían nunca. Por eso el frontend
repite el latido mientras está despierta y aquí se ignora lo que lleve callado
más de `CARA_CADUCA`. El fallo, así, es hacia contar de más: prefiero que un
aviso llegue en mal momento a que no llegue nunca.
"""
from __future__ import annotations

import time

# Lo que pidió: cinco segundos sin que se mueva el hilo para considerarlo libre.
CHAT_EN_REPOSO = 5.0

# Cuánto vale un latido de la cara. Tiene que ser holgado respecto al intervalo
# con el que el companion lo repite, para que un render lento no lo dé por
# muerto mientras el usuario está hablando.
CARA_CADUCA = 20.0

# user_id -> (despierta, cuándo se dijo)
_cara: dict[str, tuple[bool, float]] = {}

# user_id -> última vez que el hilo se movió (mensaje suyo o respuesta de Vibi)
_chat: dict[str, float] = {}


def cara(user_id: str, despierta: bool) -> None:
    """El companion dice en qué estado está. `despierta` es todo menos dormida."""
    _cara[user_id] = (despierta, time.monotonic())


def chat_se_movio(user_id: str) -> None:
    """Alguien escribió en el hilo, o Vibi acaba de contestar en él."""
    _chat[user_id] = time.monotonic()


def cara_despierta(user_id: str) -> bool:
    estado = _cara.get(user_id)
    if estado is None:
        return False
    despierta, cuando = estado
    if not despierta:
        return False
    return (time.monotonic() - cuando) <= CARA_CADUCA


def chat_en_reposo(user_id: str) -> bool:
    ultimo = _chat.get(user_id)
    if ultimo is None:
        return True
    return (time.monotonic() - ultimo) >= CHAT_EN_REPOSO


def libre(user_id: str) -> bool:
    """Si se le puede dar un turno a agy sin pisarle una conversación."""
    return not cara_despierta(user_id) and chat_en_reposo(user_id)


def por_que_ocupado(user_id: str) -> str:
    """Para el log, cuando un aviso se queda esperando."""
    if cara_despierta(user_id):
        return "la cara está despierta"
    if not chat_en_reposo(user_id):
        return "el hilo se acaba de mover"
    return ""


def olvidar(user_id: str) -> None:
    """Borra lo que se sabe de este usuario. Solo lo usan las pruebas."""
    _cara.pop(user_id, None)
    _chat.pop(user_id, None)

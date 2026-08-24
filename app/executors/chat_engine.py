"""El contrato que cumple cualquier motor de chat de Vibi.

Un motor solo sabe producir la respuesta a un turno y gestionar sus propias
sesiones vivas. Todo lo demás —conversación activa, persistencia, eventos de
la UI— lo hace `chat.py`, que es quien los usa.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChatResult:
    response: str
    artifacts: tuple[dict, ...] = ()
    telemetry: dict[str, str | int] | None = None


class ConversationChanged(RuntimeError):
    """La conversación esperada dejó de ser la activa antes de guardar el turno."""


class TrabajoEnMarcha(RuntimeError):
    """El motor dejó de poder seguir un trabajo que sigue corriendo fuera.

    No es un fallo del turno, aunque lo parezca desde dentro. Cuando el motor
    lanza un comando externo —una compilación, una instalación, otro agente
    escribiendo un proyecto— ese comando sigue su curso aunque aquí se deje de
    escuchar. Pasárselo al respaldo para que lo rehaga duplica el trabajo y
    encima se lo atribuye quien no lo hizo, que es exactamente lo que ocurrió
    el 24/08/2026 con un `claude -p` que estaba escribiendo un juego.

    `detalle` es el comando que quedó en marcha, para poder decirlo.
    """

    def __init__(self, detalle: str) -> None:
        super().__init__(detalle)
        self.detalle = detalle


class ChatEngine(Protocol):
    """Lo que Vibi necesita de un motor para poder conversar con él."""

    name: str
    display_name: str

    def conversation_lock(self, conversation_id: str) -> asyncio.Lock:
        """Serializa los turnos de una misma conversación."""

    def needs_history(self, conversation: dict) -> bool:
        """¿Hay que reinyectarle el historial porque su sesión no lo tiene?"""

    async def run_turn(
        self,
        user: dict,
        conversation: dict,
        text: str,
        attached_tool_ids: tuple[str, ...],
        turn_id: str,
        bootstrap_history: tuple[dict, ...],
        voz: bool,
        canal: str = "pwa",
    ) -> ChatResult:
        """Ejecuta el turno y devuelve la respuesta ya completa.

        `canal` dice desde dónde escribe la persona. Importa porque no todas las
        respuestas valen en todas partes: una ruta del servidor no le sirve de
        nada a quien está en el móvil, y ahí un archivo se entrega, no se enlaza.
        """

    async def close_session(self, conversation_id: str) -> None:
        """Cierra la sesión viva de esa conversación, si la hay."""

    async def invalidate_session(self, user: dict, conversation_id: str) -> None:
        """Olvida una sesión mientras quien llama ya posee su candado."""

    async def abandon_session(
        self, user: dict, conversation_id: str, motivo: str
    ) -> None:
        """Tira lo que el motor tuviera montado para este usuario tras un fallo.

        No es lo mismo que cerrar. Un motor puede querer conservar recursos
        caros entre conversaciones —`agy` tarda decenas de segundos en
        levantarse—, y eso está bien mientras el cierre sea ordenado. Cuando
        el turno ha fallado, en cambio, lo que haya montado es sospechoso:
        reutilizarlo condena a todos los turnos siguientes al mismo fallo.
        """

    async def close_all_sessions(self) -> None:
        """Cierra todo lo que el motor tenga abierto (apagado del servidor)."""

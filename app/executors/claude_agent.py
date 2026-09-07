"""Vía agéntica: Claude Agent SDK.

Flujo en dos fases, que es LA regla de seguridad de Vibi:
  1) planificar(): el agente analiza el workspace en modo plan
     (solo lectura) y produce un plan. Nada se toca.
  2) ejecutar(): solo tras aprobación explícita del usuario desde
     Telegram, el agente aplica el plan con permisos de edición.
     Nunca hace push: eso queda siempre en manos humanas.

Autenticación:
  - api: usa ANTHROPIC_API_KEY.
  - subscription: usa el login persistido de Claude Code (Pro/Max).
  - auto: prefiere API key cuando existe y, si no, usa el login persistido.

Fase 2: cada llamada se lanzará como el usuario de Linux dueño de la
tarea (sudo -u / systemd), con sus credenciales. En fase 1 corre como
el proceso del servidor.
"""
import os

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ResultMessage,
)

from .. import ai_providers
from ..claude_models import ClaudeModel, DEFAULT_CLAUDE_MODEL
from ..config import settings

INSTRUCCIONES_BASE = """Eres el agente de código de Vibi, trabajando para {nombre}.
Trabaja SOLO dentro del directorio de trabajo actual. Nunca hagas push,
ni toques configuración global de git, ni salgas del workspace.
Comunica en español, conciso y técnico."""


def _opciones_comunes(
    user_id: str,
    nombre: str,
    workspace: str,
    modelo: ClaudeModel = DEFAULT_CLAUDE_MODEL,
) -> dict:
    modo = settings.claude_auth_mode

    env: dict[str, str] = {}
    if modo == "subscription":
        # Aquí manda el login OAuth de la cuenta Pro/Max. Cualquier key —la
        # heredada por el proceso o la que el usuario haya guardado en la
        # configuración— tiene prioridad para el CLI y le hace descartar el
        # OAuth, así que se vacía sin mirar ninguna.
        env["ANTHROPIC_API_KEY"] = ""
    else:
        personal_api_key = ai_providers.get_personal_api_key(user_id, "anthropic")
        user_api_key = ai_providers.get_api_key(user_id, "anthropic")
        if modo == "api" and not user_api_key:
            raise RuntimeError(
                "CLAUDE_AUTH_MODE=api requiere ANTHROPIC_API_KEY en el .env"
            )
        if personal_api_key:
            env["ANTHROPIC_API_KEY"] = personal_api_key
        elif modo == "api" or user_api_key:
            env["ANTHROPIC_API_KEY"] = user_api_key

    return dict(
        system_prompt=INSTRUCCIONES_BASE.format(nombre=nombre),
        cwd=workspace,
        model=modelo,
        # El SDK hace `**options.env` sin comprobar None: un diccionario vacío
        # unpaquetea bien, pero `None` lo revienta con "'NoneType' object is
        # not a mapping" antes de llegar a arrancar la CLI.
        env=env,
    )


async def _recoger_texto(iterador) -> str:
    """Consume el stream del SDK y devuelve el texto final del agente."""
    partes: list[str] = []
    async for message in iterador:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    partes.append(block.text)
        elif isinstance(message, ResultMessage):
            # ResultMessage cierra la sesión; si trae resultado, es el resumen
            if getattr(message, "result", None):
                return message.result
    return "\n".join(partes) if partes else "(el agente no devolvió texto)"


async def planificar(
    user_id: str,
    nombre: str,
    workspace: str,
    prompt: str,
    modelo: ClaudeModel = DEFAULT_CLAUDE_MODEL,
) -> str:
    """Fase 1 del flujo: plan en modo solo-lectura."""
    os.makedirs(workspace, exist_ok=True)
    options = ClaudeAgentOptions(
        **_opciones_comunes(user_id, nombre, workspace, modelo),
        permission_mode="plan",  # el agente lee y razona, pero no edita
        allowed_tools=["Read", "Glob", "Grep", "Bash"],
    )
    encargo = (
        f"Tarea solicitada: {prompt}\n\n"
        "Analiza el workspace y elabora un PLAN de implementación claro y "
        "numerado (archivos a tocar, cambios, riesgos). NO apliques nada."
    )
    return await _recoger_texto(query(prompt=encargo, options=options))


async def ejecutar(
    user_id: str,
    nombre: str,
    workspace: str,
    prompt: str,
    plan: str,
    modelo: ClaudeModel = DEFAULT_CLAUDE_MODEL,
) -> str:
    """Fase 2 del flujo: ejecutar el plan ya aprobado."""
    options = ClaudeAgentOptions(
        **_opciones_comunes(user_id, nombre, workspace, modelo),
        permission_mode="acceptEdits",  # ediciones auto-aprobadas; push sigue vetado
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        disallowed_tools=[],
    )
    encargo = (
        f"Tarea original: {prompt}\n\n"
        f"Plan aprobado por el usuario:\n{plan}\n\n"
        "Aplica el plan. Si algo del plan resulta inviable, adapta lo mínimo "
        "y explícalo. Trabaja en una rama nueva de git si el workspace es un "
        "repo (git checkout -b vibi/<slug>). NUNCA hagas push. Al terminar, "
        "resume qué has cambiado y cómo verificarlo."
    )
    return await _recoger_texto(query(prompt=encargo, options=options))


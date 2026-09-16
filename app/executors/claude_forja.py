"""La forja de herramientas, delegada en Claude.

Vibi tiene dos motores de chat y hasta ahora Claude solo entraba en dos
sitios: como motor elegido y como respaldo cuando `agy` se cae. Escribir el
guion de una herramienta nueva es el tercero, y no por reparto de carga:

Una herramienta se escribe una vez y se ejecuta muchas, sin nadie mirando. Lo
que en una conversación es un tropiezo que se corrige en el turno siguiente
—una firma que no encaja, un `print` en vez de un `return`, una biblioteca que
no está instalada— aquí se queda guardado y falla cada vez. Gemini, dentro del
motor Antigravity, redactaba guiones que en la conversación parecían bien y al
guardarlos no arrancaban. Por eso este encargo sale del motor de chat, sea cual
sea, y se lo lleva Claude.

Y se lo lleva **Haiku 4.5**: es un archivo de cien líneas con un contrato fijo,
no un proyecto. Con el modelo grande la creación de una herramienta costaba
más que la tarea que la herramienta iba a ahorrar.

Este módulo solo pide el texto y lo devuelve. Validarlo, probarlo y guardarlo
es de `app/forja.py`, que es quien decide si merece entrar en el catálogo.
"""
from __future__ import annotations

import logging

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from ..config import settings
from .claude_agent import _opciones_comunes

log = logging.getLogger("vibi.forja")

# El contrato del guion. Va aquí y no en el prompt suelto porque `forja.py`
# valida exactamente esto: si cambia uno, tiene que cambiar el otro.
CONTRATO = """El guion es un único archivo de Python con una función de
entrada llamada `ejecutar`, cuyos parámetros son exactamente los que declares
en `parametros` (mismos nombres, en el mismo orden) y que devuelve un objeto
JSON serializable —un dict, idealmente—. Vibi le pone alrededor el arranque:
tú no escribes `if __name__ == "__main__"`, ni lees `sys.argv`, ni `input()`.

Reglas del guion:
- Biblioteca estándar de Python 3.11 siempre que se pueda. Instaladas y
  disponibles: httpx, pydantic. Nada más se puede dar por instalado: si te
  hace falta otra cosa, resuélvelo con la estándar.
- Sin estado entre ejecuciones: corre en un directorio temporal vacío, sin
  variables de entorno de Vibi y sin acceso a su base de datos. Si necesita
  una clave o un token, decláralo como parámetro.
- Nada interactivo, nada que espere para siempre: pon `timeout` a cualquier
  llamada de red y termina en menos de {timeout} segundos.
- Los errores previstos se devuelven como dato (`{{"error": "..."}}`), no se
  imprimen. Deja que las excepciones inesperadas suban: Vibi las registra.
- Sin comentarios de relleno ni docstrings decorativos. Código directo."""

INSTRUCCIONES = """Eres la forja de herramientas de Vibi, la asistente
personal de {nombre}.

Una herramienta de Vibi es un guion de Python que resuelve una tarea concreta
y repetitiva —convertir, calcular, consultar, dar formato— y que después se
podrá invocar muchas veces con parámetros distintos. No es un proyecto ni un
script de un solo uso: escríbelo para que valga la segunda vez.

{contrato}

Responde ÚNICAMENTE con un objeto JSON, sin texto alrededor y sin vallas de
código, con estas claves:

- `slug`: identificador en minúsculas y guiones, 3-48 caracteres.
- `nombre`: cómo se llama la herramienta para una persona (3-80 caracteres).
- `descripcion`: cuándo hay que usarla, para que otro modelo la elija sin
  probarla (30-500 caracteres). Di qué devuelve.
- `parametros`: lista de 0 a 6 objetos con `nombre` (identificador Python),
  `tipo` (`texto`, `entero`, `decimal` o `booleano`), `descripcion`,
  `obligatorio` (booleano) y `por_defecto` (solo si no es obligatorio).
- `codigo`: el archivo entero, con sus `import` arriba y la función
  `ejecutar`. Es texto JSON: escapa los saltos de línea como \\n.
- `prueba`: objeto con argumentos de ejemplo válidos con los que Vibi va a
  ejecutar el guion antes de guardarlo. Que no dependa de la red si puedes
  evitarlo, y que sea barato.
- `notas`: una frase para {nombre} sobre lo que la herramienta hace o lo que
  le falta. Vacío si no hay nada que decir.

Si la petición no se puede resolver con un guion —necesita la pantalla del
usuario, credenciales que no tienes o un servicio de pago—, responde
`{{"error": "..."}}` explicando por qué en una frase."""

ENCARGO = """Petición de {nombre}:

{peticion}"""

REHACER = """Esta herramienta ya existe y hay que rehacerla, conservando su
identificador `{slug}`. Su código actual es:

```python
{codigo}
```"""

REPARAR = """El intento anterior no sirve. Devolvió esto:

{fallo}

Corrígelo y responde otra vez con el objeto JSON completo."""


def modelo() -> str:
    """El modelo con el que se forja, configurable sin tocar el código."""
    return settings.forja_modelo or "claude-haiku-4-5"


async def _recoger_texto(iterador) -> str:
    partes: list[str] = []
    async for message in iterador:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    partes.append(block.text)
        elif isinstance(message, ResultMessage):
            if getattr(message, "result", None):
                return message.result
    return "\n".join(partes)


async def escribir(
    user_id: str,
    nombre: str,
    workspace: str,
    peticion: str,
    *,
    anterior: dict | None = None,
    fallo: str = "",
) -> str:
    """Le pide a Claude el manifiesto de la herramienta, en crudo.

    `anterior` es la herramienta que se está rehaciendo, si es que se rehace
    una. `fallo` es lo que le pasó al intento previo —JSON inválido, firma que
    no encaja, la prueba que reventó—, y es lo que convierte el segundo intento
    en algo distinto del primero en vez de en la misma tirada de dados.
    """
    opciones = _opciones_comunes(user_id, nombre, workspace, modelo())
    opciones["system_prompt"] = INSTRUCCIONES.format(
        nombre=nombre,
        contrato=CONTRATO.format(timeout=settings.forja_timeout_seconds),
    )
    partes = [ENCARGO.format(nombre=nombre, peticion=peticion)]
    if anterior:
        partes.append(
            REHACER.format(slug=anterior["slug"], codigo=anterior["codigo"])
        )
    if fallo:
        partes.append(REPARAR.format(fallo=fallo))

    options = ClaudeAgentOptions(
        **opciones,
        # No tiene que leer el workspace ni tocar nada: todo lo que necesita
        # está en el encargo. Sin herramientas tampoco hay permisos que pedir,
        # que es lo que dejaría la forja esperando a un humano que no está.
        permission_mode="plan",
        allowed_tools=[],
        disallowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    )
    return await _recoger_texto(query(prompt="\n\n".join(partes), options=options))

"""Cómo se llaman las herramientas del escritorio, dicho en una línea cada una.

`agy` no le pasa al modelo el esquema de una herramienta MCP: le deja un JSON en
`~/.gemini/antigravity-cli/mcp/vibi/` y el modelo lo abre con `view_file` antes
de la primera llamada. En la traza del 24/09/2026 —mandar un WhatsApp— se ven
**diez** `view_file` de esquemas en un turno, uno por herramienta que tocó, a
3-7 s cada uno: unos 45 s de 154 solo en averiguar qué argumentos lleva cada
cosa. El prompt ya dice cuál usar para qué; lo que faltaba era con qué.

Las firmas se sacan de los modelos de Pydantic de cada primitiva y no se
escriben a mano, para que no se queden atrás el día que cambie un argumento.
Van sin llaves porque el bloque pasa después por `str.format`.
"""
from __future__ import annotations

from .. import tools

# Las del escritorio que usa el modelo cuando maneja una aplicación, en el orden
# en que suele necesitarlas. Solo las del camino normal: el prompt tiene tope de
# tamaño, y las del ratón son el último recurso y se usan poco.
ESCRITORIO = (
    "devices.launch_app",
    "devices.ui_jev",
    "devices.ui_snapshot",
    "devices.ui_batch",
    "devices.screenshot",
    "devices.key",
)

# Los que llevan casi todas y significan siempre lo mismo: se dicen una vez en
# la cabecera en vez de en cada línea.
COMUNES = ("device", "trastienda")

# Lo que acepta `accion` en un paso de `devices.ui_batch`. El esquema dice solo
# «texto»; la lista la valida el nodo (`vibi_node.ui.ACCIONES`) y una prueba
# comprueba que esta no se ha quedado atrás.
ACCIONES_PASO = (
    "activar", "clic", "escribir", "tecla", "seleccionar", "expandir",
    "contraer", "enfocar", "desplazar", "esperar", "snapshot",
)


def _tipo(propiedad: dict) -> str:
    """El tipo de un argumento, en una palabra."""
    opciones = propiedad.get("anyOf")
    if opciones:
        tipos = [o for o in opciones if o.get("type") != "null"]
        if len(tipos) == 1:
            return _tipo(tipos[0])
    tipo = propiedad.get("type")
    if tipo == "array":
        return f"[{_tipo(propiedad.get('items') or {})}]"
    if "$ref" in propiedad:
        referencia = propiedad["$ref"].rsplit("/", 1)[-1]
        return "paso" if referencia == "UiStep" else referencia.lower()
    return {
        "string": "texto",
        "integer": "entero",
        "number": "número",
        "boolean": "sí/no",
        "object": "objeto",
    }.get(tipo, "valor")


def _argumentos(esquema: dict, omitir: tuple[str, ...] = ()) -> list[str]:
    requeridos = set(esquema.get("required") or ())
    propiedades = {
        nombre: propiedad
        for nombre, propiedad in (esquema.get("properties") or {}).items()
        if nombre not in omitir
    }
    # Primero lo obligatorio, que es lo que hay que poner siempre.
    orden = sorted(propiedades, key=lambda nombre: nombre not in requeridos)
    return [
        f"{nombre}{'' if nombre in requeridos else '?'}: "
        f"{_tipo(propiedades[nombre])}"
        for nombre in orden
    ]


def firma(tool_id: str) -> str:
    """`devices_key(key: texto, count?: entero)`, sin los `COMUNES`."""
    esquema = tools.PRIMITIVES[tool_id].input_model.model_json_schema()
    nombre = tool_id.replace(".", "_")
    return f"{nombre}({', '.join(_argumentos(esquema, COMUNES))})"


def bloque(publicadas: tuple[str, ...] | None = None) -> str:
    """Las firmas del escritorio, listas para pegar en un prompt."""
    ids = [
        tool_id
        for tool_id in ESCRITORIO
        if tool_id in tools.PRIMITIVES
        and (publicadas is None or tool_id in publicadas)
    ]
    if not ids:
        return ""
    lineas = [
        "",
        "**Argumentos**, para no abrir su esquema (`?` opcional; todas "
        "admiten además `device?` y casi todas `trastienda?`):",
    ]
    lineas.extend(f"- `{firma(tool_id)}`" for tool_id in ids)
    if "devices.ui_batch" in ids:
        paso = tools.PRIMITIVES["devices.ui_batch"].input_model.model_json_schema()
        campos = _argumentos(paso.get("$defs", {}).get("UiStep", {}))
        lineas.append(
            f"- `paso`: `{', '.join(campos)}`; accion: {', '.join(ACCIONES_PASO)}"
        )
    return "\n".join(lineas) + "\n"

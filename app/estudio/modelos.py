"""Modelos 3D curados: anatomía, máquinas, lo que no se puede calcular.

Un corazón no sale de una fórmula, y uno generado por un modelo de texto a 3D
tiene buen aspecto y las cavidades mal. Así que aquí no se genera nada: el
engine solo carga modelos que alguien ha revisado y dejado en la carpeta del
catálogo, y el agente solo puede **señalar** partes que ese modelo declara.

Vibi trae los suyos en `app/estudio/modelos_incluidos/` y se pueden añadir más
en `<datos>/estudio/modelos/` (junto a `vibi.db`), con un `catalogo.json` como
este:

    [
      {
        "id": "corazon",
        "nombre": "Corazón humano",
        "archivo": "corazon.glb",
        "fuente": "Z-Anatomy, CC BY-SA 4.0",
        "partes": {
          "Left_atrium": "Aurícula izquierda",
          "Left_ventricle": "Ventrículo izquierdo"
        }
      }
    ]

`partes` asocia el nombre de cada malla del glTF con el nombre que se le
enseña al alumno (y que puede usar el modelo para señalarla).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import settings

ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


# Los que vienen con Vibi (el corazón de Z-Anatomy). Los de `carpeta()` se
# añaden a estos y, con el mismo id, los sustituyen.
INCLUIDOS = Path(__file__).resolve().parent / "modelos_incluidos"


def carpeta() -> Path:
    return Path(settings.db_path).resolve().parent / "estudio" / "modelos"


def _leer(directorio: Path) -> list[dict]:
    manifiesto = directorio / "catalogo.json"
    if not manifiesto.is_file():
        return []
    try:
        entradas = json.loads(manifiesto.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    modelos = []
    for entrada in entradas if isinstance(entradas, list) else []:
        if not isinstance(entrada, dict):
            continue
        modelo_id = str(entrada.get("id", ""))
        archivo = str(entrada.get("archivo", ""))
        if not ID_VALIDO.match(modelo_id) or "/" in archivo or "\\" in archivo:
            continue
        if not (directorio / archivo).is_file():
            continue
        partes = entrada.get("partes") or {}
        modelos.append(
            {
                "id": modelo_id,
                "nombre": str(entrada.get("nombre") or modelo_id),
                "archivo": archivo,
                "fuente": str(entrada.get("fuente") or "catálogo local"),
                "partes": {
                    str(malla): str(etiqueta)
                    for malla, etiqueta in partes.items()
                }
                if isinstance(partes, dict)
                else {},
                "_carpeta": directorio,
            }
        )
    return modelos


def catalogo() -> list[dict]:
    """Los modelos declarados cuyo archivo existe de verdad."""
    por_id: dict[str, dict] = {}
    for directorio in (INCLUIDOS, carpeta()):
        for modelo in _leer(directorio):
            por_id[modelo["id"]] = modelo
    return list(por_id.values())


def publico(modelo: dict) -> dict:
    """Sin la ruta del servidor."""
    return {k: v for k, v in modelo.items() if not k.startswith("_")}


def buscar(modelo_id: str) -> dict | None:
    return next((m for m in catalogo() if m["id"] == modelo_id), None)


def ruta_archivo(modelo_id: str) -> Path | None:
    modelo = buscar(modelo_id)
    if modelo is None:
        return None
    base = modelo["_carpeta"].resolve()
    ruta = (base / modelo["archivo"]).resolve()
    if base not in ruta.parents:
        return None
    return ruta


def normalizar_partes(modelo: dict, pedidas: list[str]) -> tuple[list[str], list[str]]:
    """Traduce lo que pide el agente (malla o nombre) a nombres de malla.

    Un nombre puede agrupar varias mallas («Válvula aórtica» son tres valvas),
    así que una petición puede encender más de una. Devuelve las encontradas y
    las que no existen, para que el agente sepa qué señaló de verdad.
    """
    por_etiqueta: dict[str, list[str]] = {}
    for malla, etiqueta in modelo["partes"].items():
        por_etiqueta.setdefault(etiqueta.casefold(), []).append(malla)
    encontradas: list[str] = []
    desconocidas: list[str] = []
    for pedida in pedidas:
        if pedida in modelo["partes"]:
            mallas = [pedida]
        else:
            mallas = por_etiqueta.get(pedida.casefold(), [])
        if not mallas:
            desconocidas.append(pedida)
        for malla in mallas:
            if malla not in encontradas:
                encontradas.append(malla)
    return encontradas, desconocidas

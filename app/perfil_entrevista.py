"""Llegar a la entrevista con los deberes hechos.

Preguntar «¿a qué te dedicas?» a alguien cuyo disco ya lo dice es hacerle
perder el tiempo y quedarse con una respuesta peor: la gente resume mal lo que
hace. Aquí se sacan hipótesis del mapa del equipo, y la entrevista pasa de
cuestionario a confirmación —«veo carpetas de Farmacología con muchos PDF
recientes, ¿estudias medicina?»—.

**Una hipótesis nunca es una conclusión.** De una carpeta llamada `Bioquímica`
a «estudia medicina» hay un salto: podría ser docente, o de su pareja. Por eso
entran al perfil con procedencia `inventario` y confianza 0,4, y por eso se
confirman antes de valer nada.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Palabras que aparecen en nombres de carpeta y delatan un dominio. Es la
# parte determinista y corta a propósito: lo abierto lo hace el modelo con el
# mapa delante, y aquí solo está lo que se puede probar sin él.
PISTAS: dict[str, tuple[str, ...]] = {
    "medicina": ("farmacolog", "bioquimic", "anatomia", "fisiolog", "patolog", "histolog"),
    "programacion": ("repos", "proyectos", "src", "github", "workspace"),
    "derecho": ("civil", "penal", "mercantil", "procesal"),
    "audiovisual": ("premiere", "render", "footage", "proyecto de video"),
}

# Extensiones que dicen cómo trabaja alguien, no en qué. Un disco lleno de PDF
# es alguien que lee documentos largos, sea de la carrera que sea.
PISTAS_EXTENSION = {"pdf": "pdf", "docx": "documentos", "py": "codigo", "ipynb": "codigo"}

# Cuántos archivos de una extensión hacen que cuente. Tres PDF sueltos los
# tiene cualquiera; cuarenta son una forma de trabajar.
MINIMO_PARA_CONTAR = 10


@dataclass(frozen=True)
class Hipotesis:
    clase: str
    valor: str
    evidencia: str


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    return sin_tildes.encode("ascii", "ignore").decode("ascii").casefold()


def hipotesis_de(mapa: dict) -> list[Hipotesis]:
    """Qué se puede suponer de este equipo, y apoyándose en qué."""
    carpetas = (mapa or {}).get("carpetas") or []

    apoyos: dict[str, list[str]] = {}
    for carpeta in carpetas:
        nombre = _plano(str(carpeta.get("ruta", "")))
        for dominio, pistas in PISTAS.items():
            if any(pista in nombre for pista in pistas):
                apoyos.setdefault(dominio, []).append(
                    str(carpeta["ruta"]).rsplit("\\", 1)[-1]
                )

    conteo: dict[str, int] = {}
    for carpeta in carpetas:
        for extension, cuantos in (carpeta.get("extensiones") or {}).items():
            if extension in PISTAS_EXTENSION:
                conteo[extension] = conteo.get(extension, 0) + cuantos

    hipotesis = [
        Hipotesis("dominio", dominio, f"carpetas: {', '.join(carpetas_vistas[:3])}")
        for dominio, carpetas_vistas in sorted(apoyos.items())
    ]
    hipotesis += [
        Hipotesis("herramienta", extension, f"{cuantos} archivos .{extension}")
        for extension, cuantos in sorted(conteo.items())
        if cuantos >= MINIMO_PARA_CONTAR
    ]
    return hipotesis

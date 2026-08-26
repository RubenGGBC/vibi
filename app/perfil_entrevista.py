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

import re
import unicodedata
from dataclasses import dataclass

# Raíces morfológicas: must match as a prefix of a word. Examples: "farmacolog"
# matches "farmacología" but not "reposteria".
PISTAS_RAICES: dict[str, tuple[str, ...]] = {
    "medicina": ("farmacolog", "bioquimic", "fisiolog", "patolog", "histolog", "anatomia"),
}

# Palabras completas: must match as exact word, not as substring inside another word.
# Examples: "repos" matches "repos/vibi" but not "reposteria".
PISTAS_PALABRAS: dict[str, tuple[str, ...]] = {
    "programacion": ("repos", "proyectos", "src", "github", "workspace"),
    "derecho": ("civil", "penal", "mercantil", "procesal"),
    "audiovisual": ("premiere", "render", "footage"),
}

# Frases largas y específicas: pueden buscarse por subcadena porque no colisionan.
# Ejemplos: "proyecto de video" es largo y único.
PISTAS_FRASES: dict[str, tuple[str, ...]] = {
    "audiovisual": ("proyecto de video",),
}

# Extensiones que dicen cómo trabaja alguien, no en qué. Un disco lleno de PDF
# es alguien que lee documentos largos, sea de la carrera que sea.
# Los valores (pdf, documentos, codigo) se agregan y se cuentan juntos.
PISTAS_EXTENSION = {"pdf": "pdf", "docx": "documentos", "py": "codigo", "ipynb": "codigo"}

# Cuántos archivos de una extensión (agregados por su tipo) hacen que cuente.
# Tres PDF sueltos los tiene cualquiera; diez son una forma de trabajar.
MINIMO_PARA_CONTAR = 10


@dataclass(frozen=True)
class Hipotesis:
    clase: str
    valor: str
    evidencia: str


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    return sin_tildes.encode("ascii", "ignore").decode("ascii").casefold()


def _palabras_de_ruta(ruta: str) -> list[str]:
    r"""Divide una ruta en palabras, usando separadores: \, espacio, -, _."""
    plano = _plano(ruta)
    return re.split(r'[\\/_\s-]+', plano)


def _pista_en_palabras(pista: str, palabras: list[str]) -> bool:
    """Comprueba si una pista (raíz) es prefijo de alguna palabra."""
    return any(palabra.startswith(pista) for palabra in palabras)


def _pista_exacta_en_palabras(pista: str, palabras: list[str]) -> bool:
    """Comprueba si una pista es igualdad exacta con alguna palabra."""
    return pista in palabras


def hipotesis_de(mapa: dict) -> list[Hipotesis]:
    """Qué se puede suponer de este equipo, y apoyándose en qué."""
    carpetas = (mapa or {}).get("carpetas") or []

    apoyos: dict[str, list[str]] = {}
    for carpeta in carpetas:
        ruta = str(carpeta.get("ruta", ""))
        palabras = _palabras_de_ruta(ruta)

        # Buscar pistas de raíces morfológicas
        for dominio, pistas in PISTAS_RAICES.items():
            if any(_pista_en_palabras(pista, palabras) for pista in pistas):
                apoyos.setdefault(dominio, []).append(ruta.rsplit("\\", 1)[-1])

        # Buscar pistas de palabras completas
        for dominio, pistas in PISTAS_PALABRAS.items():
            if any(_pista_exacta_en_palabras(pista, palabras) for pista in pistas):
                apoyos.setdefault(dominio, []).append(ruta.rsplit("\\", 1)[-1])

        # Buscar pistas de frases largas (subcadena es aceptable aquí)
        ruta_plana = _plano(ruta)
        for dominio, pistas in PISTAS_FRASES.items():
            if any(pista in ruta_plana for pista in pistas):
                apoyos.setdefault(dominio, []).append(ruta.rsplit("\\", 1)[-1])

    # Agregar extensiones por su tipo (no por extensión individual)
    conteo_por_tipo: dict[str, int] = {}
    for carpeta in carpetas:
        for extension, cuantos in (carpeta.get("extensiones") or {}).items():
            if extension in PISTAS_EXTENSION:
                tipo = PISTAS_EXTENSION[extension]
                conteo_por_tipo[tipo] = conteo_por_tipo.get(tipo, 0) + cuantos

    hipotesis = [
        Hipotesis("dominio", dominio, f"carpetas: {', '.join(carpetas_vistas[:3])}")
        for dominio, carpetas_vistas in sorted(apoyos.items())
    ]
    hipotesis += [
        Hipotesis("herramienta", tipo, f"{cuantos} archivos .{tipo}")
        for tipo, cuantos in sorted(conteo_por_tipo.items())
        if cuantos >= MINIMO_PARA_CONTAR
    ]
    return hipotesis

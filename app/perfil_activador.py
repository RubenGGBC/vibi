"""Traducir lo que se cree del usuario a lo que el sistema enciende.

**Esto no toca nada.** Entra un perfil, sale una configuración; quien la
aplique es otro. Es una decisión de diseño y no de estilo: si activar fuera un
efecto suelto por el código, comparar «Vibi con perfil» contra «Vibi sin
perfil» exigiría dos ramas. Siendo una función pura, el grupo de control del
experimento es pasarle una lista vacía.

Y el nivel intermedio no significa lo mismo para todo, porque el transporte no
da para más: una skill puede entrar a medias —solo nombre y descripción— pero
un servidor MCP declarado expone todas sus herramientas o no está.
"""
from __future__ import annotations

from dataclasses import dataclass

# Por debajo de esto una afirmación no se le cuenta al modelo. No es el mismo
# umbral que el de las capacidades: aquí solo se decide qué se dice de ti en
# el resumen, y decir algo flojo es peor que callarlo.
MINIMO_PARA_CONTAR = 0.5


@dataclass(frozen=True)
class Configuracion:
    mcp: tuple[str, ...]
    skills_completas: tuple[str, ...]
    skills_catalogo: tuple[str, ...]
    vigilancias_activas: tuple[str, ...]
    resumen: str


def _referencias(capacidades: list[dict], tipo: str, nivel: str) -> tuple[str, ...]:
    return tuple(
        c["referencia"]
        for c in capacidades
        if c["tipo"] == tipo and c["nivel"] == nivel
    )


def _redactar(afirmaciones: list[dict]) -> str:
    """Las afirmaciones que se sostienen, en frases cortas para `GEMINI.md`."""
    # El orden es el del texto que se le enseña al modelo, y va de dentro
    # hacia fuera: quién es antes que con qué trabaja. `rasgo` es lo único que
    # describe a la persona y no a su trabajo, y por eso va arriba: si el
    # modelo solo se queda con las dos primeras líneas, que sean estas.
    encabezados = {
        "dominio": "Se dedica a",
        "rasgo": "Es",
        "herramienta": "Trabaja con",
        "preferencia": "Prefiere",
        "aficion": "Le interesa",
    }
    lineas = []
    for clase, encabezado in encabezados.items():
        valores = [
            a["valor"]
            for a in afirmaciones
            if a["clase"] == clase and a["confianza"] >= MINIMO_PARA_CONTAR
        ]
        if valores:
            lineas.append(f"{encabezado}: {', '.join(valores)}.")
    return "\n".join(lineas)


def decidir(afirmaciones: list[dict], capacidades: list[dict]) -> Configuracion:
    skills_catalogo = _referencias(capacidades, "skill", "catalogo")
    resumen = _redactar(afirmaciones)
    if skills_catalogo:
        catalogo = f"Skills disponibles bajo demanda: {', '.join(skills_catalogo)}."
        resumen = f"{resumen}\n{catalogo}".strip()
    return Configuracion(
        mcp=_referencias(capacidades, "mcp", "completo"),
        skills_completas=_referencias(capacidades, "skill", "completo"),
        skills_catalogo=skills_catalogo,
        vigilancias_activas=_referencias(capacidades, "vigilancia", "completo"),
        resumen=resumen,
    )

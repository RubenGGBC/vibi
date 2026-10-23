"""Lo que el modelo tiene que saber cuando le hablan desde Estudio.

La PWA pone «(Estudio)» o «(Estudio, paso N)» delante de todo lo que el alumno
dice en esa sección: escrito, por voz o con los botones de la escena. Que la
descripción de `estudio_nueva_escena` lo explique no basta: un modelo pequeño
ve una pregunta de física y la contesta con texto sin mirar sus herramientas.
Esto va en las reglas de cada motor, con el mismo texto.
"""
from __future__ import annotations

PREFIJO = "(Estudio"

REGLAS = """\
Viene de Estudio, donde el alumno mira un lienzo: contesta MONTANDO la
explicación con estudio_*, nunca solo con texto. Tema nuevo: empieza por
estudio_nueva_escena (el «paso N» es de la escena vieja). Sobre lo que ya hay:
estudio_ver_escena y cambia los pasos. Al terminar, una o dos frases para el
oído, sin markdown ni fórmulas."""


def es_de_estudio(texto: str) -> bool:
    return texto.lstrip().startswith(PREFIJO)

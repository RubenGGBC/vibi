"""Que los prompts se puedan formatear sin reventar.

Los system prompts pasan por `str.format()` para meter el nombre del usuario y
el del servidor MCP. Eso convierte cualquier llave del texto en un campo de
sustitución, así que escribir `{rol, nombre}` como ejemplo para el modelo
—algo perfectamente natural al documentar una herramienta— lanza un
`KeyError` y **tumba los dos motores a la vez**: antigravity falla, el
respaldo de Claude falla por lo mismo y el usuario se queda sin asistente.

Pasó el 2026-08-13 al documentar el árbol de accesibilidad. Los tests que
había no lo vieron porque comprueban el contenido de los prompts, no que se
puedan formatear.
"""
from __future__ import annotations

from unittest import TestCase

from app.executors import (
    antigravity_chat,
    claude_agent,
    claude_chat,
    claude_forja,
    groq_chat,
)


class SeFormateanSinReventar(TestCase):
    def test_personalidad_de_claude(self):
        claude_chat.PERSONALIDAD.format(nombre="Rubén")

    def test_reglas_de_claude(self):
        # La firma real, la de `_create_live_session`.
        claude_chat.REGLAS_SISTEMA.format(nombre="Rubén", servidor="pc")

    def test_reglas_de_antigravity(self):
        antigravity_chat.REGLAS_SISTEMA.format(nombre="Rubén")

    def test_personalidad_de_groq(self):
        groq_chat.PERSONALIDAD.format(nombre="Rubén")

    def test_instrucciones_del_agente(self):
        claude_agent.INSTRUCCIONES_BASE.format(nombre="Rubén")

    def test_instrucciones_de_la_forja(self):
        # Las de la forja llevan ejemplos de JSON dentro, que es exactamente
        # el texto lleno de llaves que tumbó los motores en agosto.
        instrucciones = claude_forja.INSTRUCCIONES.format(
            nombre="Rubén",
            contrato=claude_forja.CONTRATO.format(timeout=30),
        )

        self.assertIn('{"error": "..."}', instrucciones)
        self.assertNotIn('{{"error"', instrucciones)


class LasLlavesDeEjemploVanEscapadas(TestCase):
    """Un ejemplo con llaves tiene que llegar al modelo con sus llaves puestas.

    No basta con que `format` no lance: escapar de más lo dejaría con las
    dobles llaves a la vista, y escapar de menos se lleva el texto por delante
    sin avisar.
    """

    def test_el_descriptor_llega_entero_a_los_dos_motores(self):
        claude = claude_chat.REGLAS_SISTEMA.format(nombre="Rubén", servidor="pc")
        agy = antigravity_chat.REGLAS_SISTEMA.format(nombre="Rubén")

        for texto in (claude, agy):
            self.assertIn("{rol, nombre}", texto)
            self.assertNotIn("{{rol, nombre}}", texto)

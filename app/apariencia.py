"""Identidad visual de la Vibi de cada persona.

Los colores son datos del usuario, no ajustes del navegador: así la misma
Vibi aparece igual en la consola, el companion y dentro de un equipo.
"""
from __future__ import annotations

import re
import time

from . import db


COLOR_CARA = "#FFFFFF"
COLOR_ANTIFAZ = "#0C0714"
COLOR_SOMBRERO = "#F4121B"
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class AparienciaInvalida(ValueError):
    pass


def crear_tablas() -> None:
    with db._conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS user_appearance (
                   user_id          TEXT PRIMARY KEY REFERENCES users(id),
                   color_cara       TEXT NOT NULL,
                   color_antifaz    TEXT NOT NULL,
                   color_sombrero   TEXT NOT NULL,
                   actualizada_en   REAL NOT NULL
               )"""
        )


def _color(valor: object, nombre: str) -> str:
    texto = str(valor or "").strip().upper()
    if not _HEX.fullmatch(texto):
        raise AparienciaInvalida(f"{nombre} tiene que ser un color hexadecimal")
    return texto


def por_defecto() -> dict:
    return {
        "color_cara": COLOR_CARA,
        "color_antifaz": COLOR_ANTIFAZ,
        "color_sombrero": COLOR_SOMBRERO,
        "actualizada_en": 0.0,
    }


def obtener(user_id: str) -> dict:
    with db._conn() as c:
        fila = c.execute(
            "SELECT * FROM user_appearance WHERE user_id=?", (user_id,)
        ).fetchone()
    return dict(fila) if fila else {"user_id": user_id, **por_defecto()}


def guardar(user_id: str, colores: dict) -> dict:
    limpios = {
        "color_cara": _color(colores.get("color_cara"), "color_cara"),
        "color_antifaz": _color(colores.get("color_antifaz"), "color_antifaz"),
        "color_sombrero": _color(
            colores.get("color_sombrero"), "color_sombrero"
        ),
    }
    ahora = time.time()
    with db._conn() as c:
        c.execute(
            """INSERT INTO user_appearance
               (user_id,color_cara,color_antifaz,color_sombrero,actualizada_en)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                   color_cara=excluded.color_cara,
                   color_antifaz=excluded.color_antifaz,
                   color_sombrero=excluded.color_sombrero,
                   actualizada_en=excluded.actualizada_en""",
            (
                user_id,
                limpios["color_cara"],
                limpios["color_antifaz"],
                limpios["color_sombrero"],
                ahora,
            ),
        )
    return obtener(user_id)

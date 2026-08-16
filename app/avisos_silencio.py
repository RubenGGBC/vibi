"""Qué notificaciones no llegan a decirse, y cómo se explica el silencio.

El filtro es una **lista negra**, no blanca, y la decisión tiene datos detrás:
en el primer vistazo a un equipo de verdad había ocho notificaciones acumuladas
—cuatro la misma promoción de NVIDIA, dos de Xbox, una de OneDrive y un resumen
de Defender— y **ninguna era una persona escribiendo**. Con lista blanca hay que
acordarse de dar de alta cada aplicación que importa, y el día que llega el
correo del trabajo por una que no diste de alta, no te enteras. Con lista negra
el primer día es ruidoso y converge en unos pocos «esto no me lo digas más».

Las reglas viven aquí y no en el nodo porque son del usuario, no del ordenador:
silenciar las promociones de Steam en el portátil tiene que callarlas también en
el sobremesa.

**Una regla nunca calla por sí sola más de lo que dice.** Una sin aplicación ni
patrón no silencia nada, en vez de silenciarlo todo: quien las escribe es un
modelo interpretando una frase hablada, y equivocarse hacia el silencio total
sería dejar al usuario sordo sin que se entere de por qué.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Regla:
    """Un silencio. `app` vacía vale para todas; `patron` vacío, para todo.

    Las dos vacías a la vez no callan nada — ver el docstring del módulo.
    """

    app: str = ""
    patron: str = ""


def _plano(texto: object) -> str:
    """Sin tildes, sin mayúsculas y sin espacios de más.

    Se comparan formas planas porque lo que hay a cada lado lo escribieron
    personas distintas: el nombre de la aplicación lo pone quien la programó
    —«NVIDIA App»— y el patrón sale de lo que el usuario dijo en voz alta y el
    modelo transcribió, que puede llegar como «nvidia» y sin tilde.
    """
    crudo = str(texto or "")
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", crudo)
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_tildes.casefold().split())


def silencia(regla: Regla, aviso: dict) -> bool:
    """Si esta regla calla este aviso."""
    app = _plano(regla.app)
    patron = _plano(regla.patron)
    if not app and not patron:
        return False

    if app and _plano(aviso.get("app")) != app:
        return False
    if not patron:
        return True

    texto = f"{_plano(aviso.get('titulo'))} {_plano(aviso.get('cuerpo'))}"
    return patron in texto


def pasa(aviso: dict, reglas: list[Regla]) -> bool:
    """Si el aviso sobrevive a todas las reglas y merece decirse."""
    return not any(silencia(regla, aviso) for regla in reglas)


def describir(regla: Regla) -> str:
    """Cómo se lo cuenta Vibi al usuario al crear la regla.

    Decirlo en voz alta es la mitad del trato: el alcance lo elige ella, así que
    tiene que quedar claro qué acaba de callar para poder corregirla en el acto
    —«no, solo ese canal»—. Un silencio que no se anuncia es indistinguible de
    que Vibi se haya estropeado.
    """
    if regla.app and regla.patron:
        return (
            f"No vuelvo a decirte nada de {regla.app} que hable de "
            f"«{regla.patron}»."
        )
    if regla.app:
        return f"No vuelvo a decirte nada de {regla.app}."
    if regla.patron:
        return (
            f"No vuelvo a decirte nada que hable de «{regla.patron}», venga de "
            f"donde venga."
        )
    return "No he entendido qué querías callar, así que no he callado nada."

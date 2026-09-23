"""Las fechas que hay escritas en la pantalla, ya restadas contra hoy.

Esto existe por una frase del README de `awlevin/typesafe-computer-use`, que
es la advertencia honesta de todo este camino: *cada trozo de razonamiento que
el modelo grande hace gratis hay que reconstruirlo aquí como estado
determinista*. Un modelo de chat mira «13 oct» y sabe solo que faltan cuatro
semanas. Un modelo de decisión no hace calendario: elige entre las opciones
que le das, y si la opción dice «13 oct» tiene que elegir a ciegas.

Así que la resta se hace aquí, antes de preguntar, y la opción llega escrita
«13 oct — 2026-10-13 (dentro de 23 días)». Lo que antes era razonar ahora es
comparar números, que es exactamente lo que sabe hacer.

**Se lee en español y en inglés.** No por generosidad: la mitad de las
aplicaciones de este equipo están en inglés aunque el sistema esté en
español, y una pista que solo funciona en un idioma es peor que ninguna
porque no se nota cuándo deja de funcionar.

**Y `12/10/2026` es el 12 de octubre.** Aquí el día va primero, al revés que
en el repositorio del que sale esto. No es un detalle de estilo: leerlo al
revés no da error, da una fecha válida once meses equivocada.
"""
from __future__ import annotations

import re
from datetime import date

MESES = {
    # Español, por las tres primeras letras. «sept» cae en «sep» y «set» es
    # como lo abrevia media América.
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
    # Inglés. Los que coinciden ya están puestos arriba con el mismo número.
    "jan": 1, "apr": 4, "aug": 8, "dec": 12,
}
_MES = "|".join(sorted(MESES, key=len, reverse=True))
# Los guiones con los que se escribe un rango de días: «13-15 oct». Se admite
# el corriente y los dos tipográficos, que es lo que pega un calendario web.
_GUIONES = "[-–—]"

FECHA = re.compile(
    # «13 oct», «13 de octubre», «13 de octubre de 2026», «13-15 oct 2026»
    rf"\b(?:(?P<dia>\d{{1,2}})(?:\s*{_GUIONES}\s*\d{{1,2}})?\s+(?:de\s+)?"
    rf"(?P<mes>{_MES})[a-z]*\.?(?:\s+(?:de\s+)?(?P<anio>\d{{4}}))?"
    # «oct 13», «October 13, 2026»
    rf"|(?P<mes2>{_MES})[a-z]*\.?\s+(?P<dia2>\d{{1,2}})"
    rf"(?:\s*{_GUIONES}\s*\d{{1,2}})?(?:,?\s+(?P<anio2>\d{{4}}))?"
    # «2026-10-13»
    r"|(?P<iso>\d{4}-\d{2}-\d{2})"
    # «13/10/2026» y «13/10/26»: día primero, que es como se escribe aquí.
    r"|(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<a>\d{4}|\d{2}))\b",
    re.IGNORECASE,
)

# Cuánto hacia atrás puede estar una fecha sin año antes de entenderla como
# del año que viene. «31 dic» visto el 2 de enero es de hace dos días, no de
# dentro de trescientos sesenta y tres; «15 feb» visto en noviembre es del
# año que viene. El corte a dos meses es el del repositorio del que sale.
MARGEN_HACIA_ATRAS = 60


def _normalizar_mes(texto: str) -> int | None:
    return MESES.get(texto[:3].lower())


def primera(texto: str, hoy: date | None = None) -> date | None:
    """La primera fecha que hay escrita en ese texto, o `None`.

    Sin año se supone el de hoy, y el que viene si con eso quedaría demasiado
    atrás: lo que se ve en una interfaz casi siempre está por venir.
    """
    hoy = hoy or date.today()
    encontrada = FECHA.search(texto or "")
    if not encontrada:
        return None
    try:
        if encontrada.group("iso"):
            return date.fromisoformat(encontrada.group("iso"))
        if encontrada.group("d"):
            anio = int(encontrada.group("a"))
            # Un año de dos cifras es de este siglo: «13/10/26» es 2026.
            if anio < 100:
                anio += 2000
            return date(anio, int(encontrada.group("m")), int(encontrada.group("d")))
        mes = _normalizar_mes(encontrada.group("mes") or encontrada.group("mes2"))
        if mes is None:
            return None
        dia = int(encontrada.group("dia") or encontrada.group("dia2"))
        anio = encontrada.group("anio") or encontrada.group("anio2")
        hallada = date(int(anio) if anio else hoy.year, mes, dia)
        if not anio and (hoy - hallada).days > MARGEN_HACIA_ATRAS:
            hallada = hallada.replace(year=hoy.year + 1)
        return hallada
    except ValueError:
        # Un «32 de octubre» o un «13/13/2026». No es una fecha aunque lo
        # parezca, y devolver `None` es exactamente lo correcto.
        return None


def contar(cuando: date, hoy: date | None = None) -> str:
    """La fecha con la resta hecha: «2026-10-13 (dentro de 23 días)»."""
    dias = (cuando - (hoy or date.today())).days
    if dias == 0:
        return f"{cuando.isoformat()} (hoy)"
    if dias == 1:
        return f"{cuando.isoformat()} (mañana)"
    if dias == -1:
        return f"{cuando.isoformat()} (ayer)"
    if dias > 0:
        return f"{cuando.isoformat()} (dentro de {dias} días)"
    return f"{cuando.isoformat()} (hace {-dias} días)"


def pista(texto: str, hoy: date | None = None) -> str:
    """La pista que se le añade a una opción, o cadena vacía si no hay fecha."""
    cuando = primera(texto, hoy)
    return contar(cuando, hoy) if cuando else ""

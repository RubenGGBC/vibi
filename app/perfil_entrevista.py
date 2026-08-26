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

import json
import logging
import re
import unicodedata
from dataclasses import dataclass

from groq import AsyncGroq

from . import ai_providers, registro_mcp
from .config import settings

log = logging.getLogger("vibi.perfil_entrevista")

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

# Límite de longitud para las justificaciones de propuestas. El texto viene de un
# tercero (el registro oficial de MCP) y acaba en la interfaz del usuario: hay que
# acotarlo. Ver también MAX_TEXTO en avisos.py, MAX_VALOR en ui_tree.py.
MAX_JUSTIFICACION = 300

# Palabras de las respuestas libres de la entrevista (no rutas de carpeta) que
# apuntan a un término de búsqueda del registro MCP. Coinciden por palabra
# completa, igual que PISTAS_PALABRAS con las rutas: una subcadena suelta
# ("git" dentro de "digital", "nota" dentro de "anotación") daría el mismo
# falso positivo que ya se corrigió ahí.
#
# La clave es el término que se manda tal cual a `registro_mcp.buscar()`, no
# una etiqueta para enseñar a la persona — por eso va en inglés aunque las
# pistas que la disparan sean en español. El registro oficial de MCP está
# mayoritariamente en inglés: buscar "derecho" o "audiovisual" tal cual no
# encuentra nada aunque la pista se haya reconocido bien, y usar la palabra
# del dominio como si fuera un buen término de búsqueda fue el error real
# (probado en vivo el 26/08/2026: "derecho" y "audiovisual" volvían con el
# bloque «pedido» vacío).
PISTAS_TEXTO_LIBRE: dict[str, tuple[str, ...]] = {
    "pdf": ("pdf", "pdfs"),
    "notes": ("nota", "notas", "apunte", "apuntes"),
    "research": ("paper", "papers", "articulo", "articulos", "investigacion", "investigar", "bibliografia"),
    "drive": ("drive",),
    "github": ("github", "git", "repositorio", "repositorios"),
    "medicine": ("medicina", "salud", "clinico", "clinica"),
    "programming": ("programar", "programacion", "codigo", "python", "codear"),
    "legal": ("derecho", "juridico", "legal", "ley", "leyes"),
    "video": ("video", "videos", "edicion", "montaje", "audiovisual"),
    "calendar": ("calendario", "agenda", "reunion", "reuniones", "cita", "citas"),
    "email": ("correo", "email", "gmail", "outlook"),
}


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


def _palabras_de_texto(texto: str) -> list[str]:
    """Divide una respuesta libre en palabras, sin acentos y en minúsculas."""
    plano = _plano(texto)
    return re.split(r"[^a-z0-9]+", plano)


def terminos_de_texto(texto: str) -> list[str]:
    """Términos de búsqueda MCP a partir de una respuesta libre de la entrevista.

    Es la contraparte de `hipotesis_de` para texto en vez de rutas de carpeta:
    la persona escribe con sus palabras y aquí se traduce a lo que
    `registro_mcp.buscar` entiende. Devuelve una lista ordenada y sin
    duplicados; una respuesta sin ninguna pista conocida devuelve `[]` —
    decidir qué hacer con eso (un término genérico de respaldo) es cosa de
    quien llama, no de esta función.
    """
    palabras = _palabras_de_texto(texto)
    return sorted(
        termino
        for termino, pistas in PISTAS_TEXTO_LIBRE.items()
        if any(_pista_exacta_en_palabras(pista, palabras) for pista in pistas)
    )


_client: AsyncGroq | None = None


def _cliente_groq() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


PROMPT_TERMINOS = """Traduce esta respuesta libre de una entrevista a hasta 5 \
términos de búsqueda en inglés para un registro de servidores MCP (Model \
Context Protocol). El registro está mayoritariamente en inglés: usa palabras \
de búsqueda en inglés, cortas y genéricas (ej. "legal", "video editing", \
"calendar"), no una traducción literal larga.

Si la respuesta no sugiere ningún dominio o herramienta concreta, responde \
con una lista vacía. Responde solo con JSON: {{"terminos": ["...", "..."]}}.

Respuesta de la persona:
{texto}"""


async def terminos_de_texto_ia(texto: str, cliente: AsyncGroq | None = None) -> list[str]:
    """Términos de búsqueda MCP a partir del texto libre, vía un modelo de Groq.

    Sustituye a `terminos_de_texto()` (el diccionario `PISTAS_TEXTO_LIBRE`)
    cuando hay red: una docena de categorías fijas no cubre "derecho penal" ni
    cualquier dominio fuera de esa lista —probado en vivo el 26/08/2026, donde
    además usar la etiqueta de dominio tal cual como término de búsqueda dejó
    el bloque «pedido» vacío aunque la pista se detectara bien—. Un modelo
    generaliza donde una tabla no puede: la misma prueba con "oceanografía",
    que no está en ningún `PISTAS_*`, devuelve términos en inglés razonables.

    Nada cambia aguas abajo: los términos que devuelve pasan igual por
    `proponer()`, que verifica cada servidor antes de proponerlo — este
    modelo solo elige qué buscar, nunca qué instalar ni qué aprobar. Si Groq
    falla, tarda o devuelve algo que no se puede leer, se cae a
    `terminos_de_texto()` para que la entrevista nunca dependa de que una red
    externa responda.
    """
    texto = texto.strip()
    if not texto:
        return []
    try:
        resp = await (cliente or _cliente_groq()).chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "user", "content": PROMPT_TERMINOS.format(texto=texto[:2000])}
            ],
            temperature=0.0,
            max_tokens=200,
            response_format={"type": "json_object"},
            **ai_providers.opciones_groq(settings.groq_model),
        )
        datos = json.loads(resp.choices[0].message.content or "{}")
        terminos = datos.get("terminos", [])
        if not isinstance(terminos, list):
            raise ValueError("«terminos» no es una lista")
        limpios: list[str] = []
        for t in terminos:
            if not isinstance(t, str):
                continue
            t = re.sub(r"[^a-z0-9 ]", "", t.strip().lower())[:40]
            if t and t not in limpios:
                limpios.append(t)
        return limpios[:5]
    except Exception as error:
        log.warning("Groq no dio términos usables, uso el diccionario: %s", error)
        return terminos_de_texto(texto)


def _recortar_justificacion(texto: str) -> str:
    """Recorta un texto a MAX_JUSTIFICACION de forma legible.

    Si el texto excede el límite, lo trunca sin cortar a mitad de palabra y añade
    elipsis. Si cabe, devuelve el texto sin cambios.
    """
    if len(texto) <= MAX_JUSTIFICACION:
        return texto

    # Truncar dejando espacio para la elipsis (…)
    limite = MAX_JUSTIFICACION - 1
    truncado = texto[:limite]

    # No cortar a mitad de palabra: buscar el último espacio antes del límite
    ultimo_espacio = truncado.rfind(" ")
    if ultimo_espacio > 0:
        truncado = truncado[:ultimo_espacio]

    return truncado + "…"


@dataclass(frozen=True)
class Propuesta:
    tipo: str
    referencia: str
    titulo: str
    justificacion: str
    transporte: str
    bloque: str


def proponer(
    terminos_pedidos: list[str],
    terminos_adyacentes: list[str],
    buscador=None,
    verificador=None,
) -> list[Propuesta]:
    """Lo que se le enseña al usuario para que apruebe, en dos montones.

    **Separar los dos bloques no es cosmético.** «Esto te lo pongo porque me lo
    has pedido» y «esto además lo he encontrado yo» merecen niveles de
    confianza distintos por parte de quien lee, y mezclarlos hace que la
    expansión contamine lo pedido.

    Nada llega aquí sin verificarse: proponer lo no comprobado empeora el
    sistema, porque el usuario aprueba dando por hecho que se miró. Un rechazo
    es definitivo dentro de la misma propuesta: un servidor que falla en un
    bloque no se reintenta en otro, ni con otro término del mismo bloque.
    """
    buscar = buscador or registro_mcp.buscar
    verificar = verificador or registro_mcp.verificar

    propuestas: list[Propuesta] = []
    ya_vistos: set[str] = set()

    for bloque, terminos in (("pedido", terminos_pedidos), ("encaja", terminos_adyacentes)):
        for termino in terminos:
            for servidor in buscar(termino):
                if servidor.nombre in ya_vistos:
                    continue
                # Marcar como visto antes de verificar, para capturar también los rechazos.
                # Un rechazo es definitivo dentro de la misma propuesta.
                ya_vistos.add(servidor.nombre)
                vale, _motivo = verificar(servidor)
                if not vale:
                    continue
                propuestas.append(
                    Propuesta(
                        tipo="mcp",
                        referencia=servidor.nombre,
                        titulo=servidor.titulo,
                        justificacion=_recortar_justificacion(servidor.descripcion),
                        transporte=servidor.transporte,
                        bloque=bloque,
                    )
                )
    return propuestas

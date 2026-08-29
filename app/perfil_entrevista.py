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
de búsqueda en inglés.

Es un registro público y grande: una palabra genérica de una sola sílaba de \
concepto ("automation", "search", "email", "notifications") encuentra de todo \
menos lo que quieres —contratos legales, datos de criptomonedas, marketing— \
porque coincide por texto, no por relevancia. Prefiere frases de 2-3 palabras \
que acoten el terreno concreto (mejor "browser automation" o "test automation" \
que "automation" a secas; mejor "calendar scheduling" que "calendar"). Solo usa \
una palabra sola cuando el dominio ya es estrecho de por sí (ej. "legal", \
"oceanography").

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


# Clases de afirmación válidas para lo que salga de la conversación de
# entrevista. Coincide con perfil.CLASES; se repite aquí para no acoplar este
# módulo al de persistencia solo por una validación.
CLASES_AFIRMACION_ENTREVISTA = frozenset({"dominio", "herramienta", "preferencia", "aficion"})

# Las mismas cuatro preguntas que antes vivían en el formulario estático,
# ahora como respaldo cuando Groq no responde. La entrevista conversacional
# nunca debe depender de que una red externa esté disponible.
GUION_FIJO: tuple[str, ...] = (
    "¿Para qué vas a usar Vibi?",
    "¿Qué esperas de ella?",
    "¿En qué te gustaría que te ayudara y hoy haces a mano?",
    "Cuéntame algo libre: aficiones, preferencias, lo que quieras.",
)

# Techo de turnos de Vibi antes de forzar el cierre. Es una válvula de
# seguridad, no el camino esperado: con Groq funcionando la entrevista cierra
# sola bastante antes al cubrir los cuatro temas del prompt.
MAX_TURNOS_VIBI = 8

PROMPT_TURNO = """Eres Vibi dirigiendo una breve entrevista hablada para conocer \
a quien te va a usar.

Cubre estos cuatro temas, uno cada vez, en el orden que tenga más sentido según \
lo que te cuenten:
1. Para qué va a usar Vibi.
2. Qué espera de ella.
3. Qué le gustaría delegarte que hoy hace a mano.
4. Algo libre: aficiones, preferencias, lo que quiera contarte.

Habla en español, en una o dos frases, como en una conversación real: nada de \
listas ni markdown. Si una respuesta es muy corta o vaga, puedes repreguntar UNA \
vez sobre ese tema antes de pasar al siguiente. En cuanto hayas cubierto los \
cuatro temas razonablemente, cierra con una frase breve de agradecimiento y \
marca terminado. No alargues la entrevista más de lo necesario.

Responde siempre con JSON.

Mientras la entrevista siga:
{{"vibi_dice": "...", "terminado": false}}

Al cerrarla, el resumen alimenta una búsqueda de herramientas: no lo conviertas \
en un diario de aficiones.
- "afirmaciones": lo de los temas 1 a 3 (para qué la usa, qué espera, qué quiere \
delegar) va con clase "preferencia" — casi siempre debería haber al menos una. \
Solo lo del tema 4 (aficiones, gustos personales) va con clase "aficion".
- "texto_libre": 2-4 frases centradas en QUÉ VA A HACER con Vibi y qué tareas o \
dominios de trabajo mencionó (temas 1 a 3) — eso es lo que se busca en un \
registro de herramientas. Las aficiones del tema 4 mencionalas solo si de verdad \
sugieren una herramienta relacionada (por ejemplo "toca la guitarra" no aporta \
nada que buscar; "edita vídeo con Premiere" sí).

{{"vibi_dice": "frase de cierre", "terminado": true, "resumen": {{
  "afirmaciones": [{{"clase": "preferencia o aficion", "valor": "..."}}],
  "texto_libre": "..."
}}}}"""


def _respuestas_de(historial: list[dict]) -> list[str]:
    return [
        str(t.get("texto", "")).strip()
        for t in historial
        if t.get("rol") == "usuario" and str(t.get("texto", "")).strip()
    ]


def _turno_guion_fijo(historial: list[dict]) -> dict:
    """Entrevista de respaldo: las mismas cuatro preguntas de siempre, en
    orden, sin repreguntas. Es lo que responde `turno_entrevista` cuando Groq
    no está disponible, así que este paso nunca depende de la red.
    """
    hechas = sum(1 for t in historial if t.get("rol") == "vibi")
    if hechas < len(GUION_FIJO):
        return {"vibi_dice": GUION_FIJO[hechas], "terminado": False}

    respuestas = _respuestas_de(historial)
    afirmaciones = []
    if respuestas:
        afirmaciones.append({"clase": "preferencia", "valor": respuestas[0][:200]})
    if len(respuestas) > 1:
        afirmaciones.append({"clase": "aficion", "valor": respuestas[-1][:200]})
    return {
        "vibi_dice": "Gracias, con esto tengo para buscarte lo que necesitas.",
        "terminado": True,
        "resumen": {
            "afirmaciones": afirmaciones,
            "texto_libre": " ".join(respuestas)[:1000],
        },
    }


def _mensajes_de_historial(historial: list[dict]) -> list[dict]:
    mensajes = [{"role": "system", "content": PROMPT_TURNO}]
    for turno in historial:
        texto = str(turno.get("texto", "")).strip()
        if not texto:
            continue
        rol = "assistant" if turno.get("rol") == "vibi" else "user"
        mensajes.append({"role": rol, "content": texto[:2000]})
    return mensajes


def _limpiar_resumen(bruto: object) -> dict:
    afirmaciones: list[dict] = []
    texto_libre = ""
    if isinstance(bruto, dict):
        crudas = bruto.get("afirmaciones")
        for item in crudas if isinstance(crudas, list) else []:
            if not isinstance(item, dict):
                continue
            clase = item.get("clase")
            valor = str(item.get("valor", "")).strip()[:200]
            if clase in CLASES_AFIRMACION_ENTREVISTA and valor:
                afirmaciones.append({"clase": clase, "valor": valor})
        texto_libre = str(bruto.get("texto_libre", "")).strip()[:1000]
    return {"afirmaciones": afirmaciones[:5], "texto_libre": texto_libre}


async def turno_entrevista(historial: list[dict], cliente: AsyncGroq | None = None) -> dict:
    """Un turno de la entrevista hablada del paso 2: la pregunta de Vibi (o el
    cierre con resumen), a partir de lo que ya se ha dicho.

    `historial` es la conversación hasta ahora, `[{"rol": "vibi"|"usuario",
    "texto": str}, ...]`; vacío para el primer turno. El modelo decide cuándo
    ya cubrió los cuatro temas del prompt y devuelve el resumen estructurado
    que hoy alimenta `irABusqueda()` y `handleFinalizar()` en el cliente — no
    cambia su forma, solo de dónde sale.

    Si Groq falla, tarda o devuelve algo ilegible, cae a `_turno_guion_fijo`:
    las mismas cuatro preguntas fijas de siempre, sin repreguntas. La
    conversación en curso no se pierde porque el guion fijo también lee el
    historial para saber por dónde va y qué respuestas ya hay.
    """
    if sum(1 for t in historial if t.get("rol") == "vibi") >= MAX_TURNOS_VIBI:
        return _turno_guion_fijo(historial)
    try:
        resp = await (cliente or _cliente_groq()).chat.completions.create(
            model=settings.groq_model,
            messages=_mensajes_de_historial(historial),
            temperature=0.4,
            max_tokens=400,
            response_format={"type": "json_object"},
            **ai_providers.opciones_groq(settings.groq_model),
        )
        datos = json.loads(resp.choices[0].message.content or "{}")
        vibi_dice = str(datos.get("vibi_dice", "")).strip()
        if not vibi_dice:
            raise ValueError("«vibi_dice» vacío")
        terminado = bool(datos.get("terminado", False))
        resultado = {"vibi_dice": vibi_dice, "terminado": terminado}
        if terminado:
            resultado["resumen"] = _limpiar_resumen(datos.get("resumen"))
        return resultado
    except Exception as error:
        log.warning("Groq no dio un turno de entrevista usable, uso el guion fijo: %s", error)
        return _turno_guion_fijo(historial)


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

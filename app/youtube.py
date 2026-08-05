"""Resolver qué vídeo de YouTube quiere alguien, sin API key.

Morgana no puede adivinar la URL de un vídeo: si le pides una canción, lo más
que sabe construir es una búsqueda, y abrirte una lista de resultados no es lo
que pediste. Este módulo cierra ese hueco.

Nada de lo que sale de aquí es texto libre que acabe en el contexto del modelo:
se devuelven identificadores validados contra un patrón estricto y las URLs se
construyen aquí. Un título malicioso no puede convertirse en otra cosa que un
título recortado.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx

BUSQUEDA = "https://www.youtube.com/results"
FEED = "https://www.youtube.com/feeds/videos.xml"

# Sin esto, desde la UE todo redirige al muro de consentimiento y la respuesta
# no trae ni un solo vídeo.
COOKIES = {"SOCS": "CAI", "CONSENT": "YES+cb"}
CABECERAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "es-ES,es;q=0.9",
}

# Filtro de la búsqueda que devuelve solo canales, no vídeos sueltos.
SOLO_CANALES = "EgIQAg%3D%3D"

ID_VIDEO = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')
ID_CANAL = re.compile(r'"browseId":"(UC[A-Za-z0-9_-]{22})"')
ID_CANAL_EXACTO = re.compile(r"UC[A-Za-z0-9_-]{22}")

# Espacios de nombres del feed Atom de YouTube.
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}

TIEMPO_ESPERA = 15.0


class YoutubeError(Exception):
    pass


@dataclass(frozen=True)
class Video:
    video_id: str
    titulo: str | None
    publicado: str | None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def _limpiar(texto: str, limite: int = 120) -> str:
    """Un título es texto de un desconocido: se recorta y se aplana."""
    plano = " ".join(texto.split())
    return plano[:limite]


def _descodificar(crudo: str) -> str:
    """Deshace los escapes del JSON incrustado en la página.

    Con `unicode_escape` no vale: trata los bytes como latin-1 y parte en dos
    los pares suplentes, así que «lofi hip hop radio \\ud83d\\udcda beats» salía
    como «lofi hip hop radio ð beats». Dejarlo así no era solo feo —Morgana lee
    ese título en voz alta— sino que rompía el emparejamiento por título al
    darle al play. El propio analizador de JSON sabe hacerlo bien.
    """
    try:
        valor = json.loads(f'"{crudo}"')
    except json.JSONDecodeError:
        return crudo
    return valor if isinstance(valor, str) else crudo


def _pedir(url: str, params: dict | None = None) -> str:
    try:
        respuesta = httpx.get(
            url,
            params=params,
            headers=CABECERAS,
            cookies=COOKIES,
            timeout=TIEMPO_ESPERA,
            follow_redirects=True,
        )
        respuesta.raise_for_status()
    except httpx.HTTPError as error:
        raise YoutubeError(f"No he podido consultar YouTube: {error}") from error
    return respuesta.text


def buscar_video(consulta: str) -> Video:
    """El primer resultado de buscar algo, que es lo que abriría una persona."""
    consulta = " ".join(str(consulta or "").split())
    if not consulta:
        raise YoutubeError("No has dicho qué quieres ver")

    cuerpo = _pedir(BUSQUEDA, {"search_query": consulta})
    encontrados = ID_VIDEO.findall(cuerpo)
    if not encontrados:
        raise YoutubeError(f"YouTube no me devuelve nada para «{consulta}»")

    video_id = encontrados[0]
    # El título vive lejos del id en el HTML; se busca aparte y, si no aparece,
    # tampoco pasa nada: lo importante es el vídeo.
    titulo = None
    marca = re.search(
        r'"videoId":"' + video_id + r'".{0,2000}?'
        r'"title":\{"runs":\[\{"text":"(.{3,120}?)"\}',
        cuerpo,
        re.S,
    )
    if marca:
        titulo = _limpiar(_descodificar(marca.group(1)))
    return Video(video_id, titulo, None)


def resolver_canal(nombre: str) -> str:
    """Del nombre que diría una persona al identificador del canal."""
    nombre = " ".join(str(nombre or "").split())
    if not nombre:
        raise YoutubeError("No has dicho de qué canal")

    cuerpo = _pedir(BUSQUEDA, {"search_query": nombre, "sp": SOLO_CANALES})
    encontrados = ID_CANAL.findall(cuerpo)
    if not encontrados:
        raise YoutubeError(f"No encuentro ningún canal llamado «{nombre}»")
    return encontrados[0]


def ultimo_video(canal: str) -> Video:
    """El vídeo más reciente de un canal.

    El feed suele venir ya ordenado, pero aquí se ordena por fecha igualmente:
    es una garantía que YouTube no promete en ninguna parte, y confiar en el
    orden de llegada es justo cómo se acaba abriendo un vídeo de hace años.
    """
    channel_id = (
        canal if ID_CANAL_EXACTO.fullmatch(canal or "") else resolver_canal(canal)
    )
    cuerpo = _pedir(FEED, {"channel_id": channel_id})

    # Se parsea como el XML que es. A mano, cualquier `.*?` entre campos se cuela
    # en la entrada siguiente y acabas emparejando un vídeo con la fecha de otro.
    try:
        raiz = ElementTree.fromstring(cuerpo)
    except ElementTree.ParseError as error:
        raise YoutubeError("YouTube ha devuelto un feed que no entiendo") from error

    entradas: list[Video] = []
    for entrada in raiz.findall("atom:entry", NS):
        video_id = entrada.findtext("yt:videoId", default="", namespaces=NS).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            continue
        entradas.append(
            Video(
                video_id,
                _limpiar(entrada.findtext("atom:title", "", NS) or ""),
                (entrada.findtext("atom:published", "", NS) or "").strip(),
            )
        )

    if not entradas:
        raise YoutubeError("Ese canal no tiene vídeos publicados")

    return max(entradas, key=lambda entrada: entrada.publicado or "")

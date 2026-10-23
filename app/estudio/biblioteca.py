"""La biblioteca de objetos: modelos 3D hechos por personas, no por el agente.

Un coche montado con cajas y cilindros por el agente sale con las ruedas de
pie y la flecha metida en la carrocería: componer geometría a ciegas, por
coordenadas, es lo que peor hace un modelo de lenguaje. Así que para los
objetos del mundo (vehículos, herramientas, muebles, naves, árboles, comida…)
hay una biblioteca de modelos de verdad.

Son los kits 3D de Kenney (https://kenney.nl), con licencia CC0. Como el atlas:

- El **índice** (`biblioteca/indice.json`, versionado) dice qué hay: cada
  modelo con sus medidas y sus partes con nombre (las ruedas de un coche son
  nodos propios, con el pivote en el eje, así que se pueden hacer girar).
- La **geometría** se descarga **bajo demanda**, el kit entero la primera vez
  que se pide uno de sus modelos, y queda en `<datos>/estudio/biblioteca/`.
  Las texturas se meten dentro de cada `.glb` al instalarlo, para que el
  cliente cargue un solo archivo.

`scripts/estudio_preparar_biblioteca.py` descarga todos los kits de golpe y
regenera el índice.
"""
from __future__ import annotations

import asyncio
import io
import json
import math
import posixpath
import re
import struct
import zipfile
from functools import lru_cache
from pathlib import Path

import httpx

from ..config import settings

INDICE = Path(__file__).resolve().parent / "biblioteca" / "indice.json"
TIMEOUT = 60.0
MAX_ZIP = 40 * 1024 * 1024
ID_VALIDO = re.compile(r"^([a-z0-9-]{1,40})/([A-Za-z0-9_.-]{1,80})$")

FUENTE = "Kenney (kenney.nl), CC0"

# Cada kit: su página (de ahí se saca el enlace de descarga si el guardado
# caduca), el enlace conocido y las palabras con las que se le encuentra.
KITS: dict[str, dict] = {
    "car-kit": {
        "url": "https://kenney.nl/media/pages/assets/car-kit/1a312ec241-1775131960/kenney_car-kit.zip",
        "tema": "vehículos: coches, camiones, karts, tractores, ambulancia, policía, ruedas, conos",
        "claves": "vehicle car coche vehiculo auto truck camion wheel rueda",
    },
    "space-kit": {
        "url": "https://kenney.nl/media/pages/assets/space-kit/20874c75ac-1677698978/kenney_space-kit.zip",
        "tema": "espacio: cohetes por piezas, naves, rover, astronautas, antenas, meteoritos, cráteres",
        "claves": "space espacio rocket cohete nave satelite astronauta",
    },
    "pirate-kit": {
        "url": "https://kenney.nl/media/pages/assets/pirate-kit/e6d4bb1525-1771333093/kenney_pirate-kit.zip",
        "tema": "barcos y puerto: barcos de vela y de remos, cañones, balas de cañón, barriles, cofres",
        "claves": "ship barco boat bote cannon canon pirate pirata",
    },
    "train-kit": {
        "url": "https://kenney.nl/media/pages/assets/train-kit/cf8521d625-1727040883/kenney_train-kit.zip",
        "tema": "trenes: locomotoras, vagones, vías",
        "claves": "train tren rail via locomotive locomotora wagon vagon",
    },
    "prototype-kit": {
        "url": "https://kenney.nl/media/pages/assets/prototype-kit/4d3b7073ed-1724832076/kenney_prototype-kit.zip",
        "tema": "prototipos: formas básicas, rampas, escaleras, palancas, botones, dianas, tuberías, números",
        "claves": "prototype prototipo shape forma ramp rampa lever palanca",
    },
    "survival-kit": {
        "url": "https://kenney.nl/media/pages/assets/survival-kit/4065a8185b-1712149243/kenney_survival-kit.zip",
        "tema": "herramientas y campamento: hacha, martillo, pico, pala, yunque, tienda, hoguera, troncos",
        "claves": "tool herramienta camp campamento survival",
    },
    "furniture-kit": {
        "url": "https://kenney.nl/media/pages/assets/furniture-kit/440e0608a4-1677580847/kenney_furniture-kit.zip",
        "tema": "casa: muebles, electrodomésticos, lámparas, baño, cocina",
        "claves": "furniture mueble casa house room habitacion",
    },
    "food-kit": {
        "url": "https://kenney.nl/media/pages/assets/food-kit/83086fa91c-1719418518/kenney_food-kit.zip",
        "tema": "comida: frutas, verduras, platos, utensilios de cocina",
        "claves": "food comida fruit fruta vegetable verdura",
    },
    "nature-kit": {
        "url": "https://kenney.nl/media/pages/assets/nature-kit/37ac38a37b-1677698939/kenney_nature-kit.zip",
        "tema": "naturaleza: árboles, plantas, flores, rocas, setas, terreno",
        "claves": "nature naturaleza tree arbol plant planta rock roca",
    },
    "platformer-kit": {
        "url": "https://kenney.nl/media/pages/assets/platformer-kit/1585cf62b4-1775122253/kenney_platformer-kit.zip",
        "tema": "juego de plataformas: bloques, muelles, banderas, monedas, llaves, cajas",
        "claves": "platformer plataforma block bloque spring muelle",
    },
}

# El agente busca en inglés, como en el atlas; esto recoge lo más común si lo
# hace en español. No pretende ser un diccionario.
SINONIMOS = {
    "coche": "car sedan", "car": "car sedan hatchback", "auto": "car", "camion": "truck", "camión": "truck",
    "rueda": "wheel", "ruedas": "wheel", "furgoneta": "van", "cohete": "rocket",
    "nave": "craft ship", "barco": "ship boat", "bote": "boat", "cañon": "cannon",
    "cañón": "cannon", "bala": "ball", "barril": "barrel", "cofre": "chest",
    "tren": "train", "locomotora": "locomotive", "vagon": "wagon", "vagón": "wagon",
    "rampa": "ramp slope", "palanca": "lever", "boton": "button", "botón": "button",
    "diana": "target", "tuberia": "pipe", "tubería": "pipe", "escalera": "stairs ladder",
    "martillo": "hammer", "hacha": "axe", "pala": "shovel", "pico": "pickaxe",
    "yunque": "anvil", "hoguera": "campfire", "tienda": "tent", "tronco": "log",
    "silla": "chair", "mesa": "table", "cama": "bed", "lampara": "lamp",
    "lámpara": "lamp", "nevera": "fridge", "frigorifico": "fridge",
    "frigorífico": "fridge", "lavadora": "washer", "televisor": "television",
    "tele": "television", "arbol": "tree", "árbol": "tree", "flor": "flower",
    "roca": "rock", "piedra": "stone rock", "seta": "mushroom", "manzana": "apple",
    "platano": "banana", "plátano": "banana", "pan": "bread", "muelle": "spring",
    "resorte": "spring", "bandera": "flag", "moneda": "coin", "llave": "key",
    "caja": "box crate", "astronauta": "astronaut", "antena": "dish satellite",
    "meteorito": "meteor", "crater": "crater", "cráter": "crater", "policia": "police",
    "policía": "police", "ambulancia": "ambulance", "bomberos": "firetruck",
    "tractor": "tractor", "taxi": "taxi", "cono": "cone", "carro": "cart",
}


class BibliotecaError(ValueError):
    """Lo que el agente tiene que saber para no inventarse el objeto."""


# --- El índice -----------------------------------------------------------------


@lru_cache(maxsize=1)
def indice() -> dict[str, dict]:
    if not INDICE.is_file():
        return {}
    datos = json.loads(INDICE.read_text(encoding="utf-8"))
    return {m["id"]: m for m in datos["modelos"]}


def ficha(modelo_id: str) -> dict | None:
    return indice().get(modelo_id) or externos().get(modelo_id)


# --- Modelos importados de fuera (Sketchfab) ----------------------------------
#
# No van en el índice versionado: se importan cuando el agente pide uno y su
# ficha queda en `<datos>/estudio/biblioteca/externos.json`, junto al .glb.
# Desde ahí son un modelo más: partes, giros, ajustes y la misma URL.


def _ruta_externos() -> Path:
    return carpeta() / "externos.json"


_externos: dict[str, dict] | None = None


def externos() -> dict[str, dict]:
    global _externos
    if _externos is None:
        try:
            _externos = json.loads(_ruta_externos().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _externos = {}
    return _externos


def registrar_externo(ficha_nueva: dict, glb: bytes) -> dict:
    """Guarda el .glb y su ficha. Escritura atómica: un corte no deja medio índice."""
    destino = carpeta() / ficha_nueva["kit"] / f"{ficha_nueva['nombre']}.glb"
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".tmp")
    temporal.write_bytes(glb)
    temporal.replace(destino)
    todos = {**externos(), ficha_nueva["id"]: ficha_nueva}
    ruta_indice = _ruta_externos()
    temporal = ruta_indice.with_suffix(".tmp")
    temporal.write_text(json.dumps(todos, ensure_ascii=False), encoding="utf-8")
    temporal.replace(ruta_indice)
    global _externos
    _externos = todos
    return ficha_nueva


def olvidar_externos() -> None:
    """Para las pruebas: vuelve a leer del disco."""
    global _externos
    _externos = None


def _palabras(texto: str) -> list[str]:
    # «hatchback-sports», «craft_speederA» → hatchback, sports, craft, speeder, a
    texto = re.sub(r"([a-z])([A-Z])", r"\1 \2", texto)
    return [p for p in re.split(r"[^0-9a-zá-úñ]+", texto.casefold()) if p]


def buscar(consulta: str, limite: int = 25) -> dict:
    """Modelos cuyo nombre o kit contienen las palabras de la consulta."""
    pedidas: list[str] = []
    for palabra in _palabras(consulta):
        pedidas.extend(_palabras(SINONIMOS.get(palabra, palabra)))
    if not pedidas:
        raise BibliotecaError("Consulta vacía")

    def puntos(modelo: dict) -> int:
        propias = _palabras(modelo.get("titulo") or modelo["nombre"])
        del_kit = _palabras(KITS.get(modelo["kit"], {}).get("claves", ""))
        total = 0
        for p in pedidas:
            if p in propias:
                total += 3
            elif len(p) >= 4 and any(
                w.startswith(p) or p.startswith(w) for w in propias if len(w) >= 4
            ):
                # «wheels» encuentra «wheel», pero «car» no encuentra «carrot».
                total += 2
            elif p in del_kit:
                total += 1
        return total

    # Los importados (Sketchfab, PartNet) también: ya están en disco.
    candidatos = [(puntos(m), m) for m in [*indice().values(), *externos().values()]]
    candidatos = [(s, m) for s, m in candidatos if s > 0]
    candidatos.sort(key=lambda c: (-c[0], len(c[1]["nombre"]), c[1]["id"]))
    return {
        "modelos": [publico(m) for _, m in candidatos[:limite]],
        "total": len(candidatos),
    }


# Qué hace cada pieza según su nombre. En Kenney el pivote está donde toca
# (la bisagra de la puerta, el eje de la rueda), así que basta con el eje.
PISTAS = (
    (re.compile(r"wheel", re.I), "giro x (rueda)"),
    (re.compile(r"door|gate", re.I), "giro y (bisagra: abre con 90 o -90)"),
    (re.compile(r"drawer", re.I), "desliza z (cajón)"),
    (re.compile(r"lid|cover", re.I), "giro x o z (tapa)"),
    (re.compile(r"handle|lever", re.I), "giro x (palanca, ±45)"),
    (re.compile(r"turret|rotate-y", re.I), "giro y (torreta)"),
    (re.compile(r"arm|shovel|spoiler", re.I), "giro x (brazo)"),
)


def articulables(modelo: dict) -> dict[str, str]:
    pistas = {}
    for parte in modelo["partes"]:
        for patron, pista in PISTAS:
            if patron.search(parte):
                pistas[parte] = pista
                break
    return pistas


def publico(modelo: dict) -> dict:
    """Lo que necesita el agente para colocarlo sin adivinar."""
    ancho, alto, largo = modelo["medidas"]
    datos = {
        "id": modelo["id"],
        "medidas": {"ancho_x": ancho, "alto_y": alto, "largo_z": largo},
        "partes": modelo["partes"],
    }
    if modelo.get("titulo"):
        datos["titulo"] = modelo["titulo"]
    if modelo.get("generado"):
        datos["generado"] = True
    pistas = articulables(modelo)
    if pistas:
        datos["articulables"] = pistas
    if modelo.get("articulaciones_sugeridas"):
        datos["articulado"] = (
            f"{len(modelo['articulaciones_sugeridas'])} articulaciones de serie (con sus topes): "
            "el alumno las mueve con el ratón"
        )
    return datos


def fuente(modelo: dict) -> tuple[str, str | None]:
    """Cómo se cita en la procedencia, y el enlace a su página si lo hay."""
    if modelo.get("autor"):
        return (
            f"«{modelo['titulo']}», de {modelo['autor']} en {modelo.get('plataforma', 'Sketchfab')} "
            f"({modelo['licencia']})",
            modelo.get("pagina"),
        )
    return f"{FUENTE}: {modelo['id']}", None


async def preparar(modelo_id: str) -> dict:
    """La ficha del modelo con su archivo ya en disco.

    Un id de Sketchfab que aún no está se importa aquí (pide red y token); uno
    de Kenney descarga su kit si falta.
    """
    if modelo_id.startswith("sketchfab/") and ruta(modelo_id) is None:
        from . import sketchfab  # noqa: PLC0415

        await sketchfab.importar(modelo_id.split("/", 1)[1])
    modelo = ficha(modelo_id)
    if modelo is None:
        raise BibliotecaError(
            f"«{modelo_id}» no está en la biblioteca: búscalo con estudio_biblioteca"
        )
    await asegurar(modelo_id)
    return modelo


def kits() -> list[dict]:
    cuenta: dict[str, int] = {}
    for m in indice().values():
        cuenta[m["kit"]] = cuenta.get(m["kit"], 0) + 1
    return [
        {"kit": kit, "contiene": datos["tema"], "modelos": cuenta.get(kit, 0)}
        for kit, datos in KITS.items()
    ]


def expandir_partes(modelo: dict, patrones: list[str]) -> tuple[list[str], list[str]]:
    """Nombres o prefijos con * («wheel*») → partes del modelo. Y las que no casan."""
    partes: list[str] = []
    sueltos: list[str] = []
    for patron in patrones:
        if patron.endswith("*"):
            casan = [p for p in modelo["partes"] if p.startswith(patron[:-1])]
        else:
            casan = [p for p in modelo["partes"] if p == patron]
        if not casan:
            sueltos.append(patron)
        for p in casan:
            if p not in partes:
                partes.append(p)
    return partes, sueltos


# --- Los archivos --------------------------------------------------------------


def carpeta() -> Path:
    return Path(settings.db_path).resolve().parent / "estudio" / "biblioteca"


def ruta(modelo_id: str) -> Path | None:
    """El .glb instalado, solo si el id está en el índice (nada de rutas libres)."""
    modelo = ficha(modelo_id)
    if modelo is None:
        return None
    archivo = carpeta() / modelo["kit"] / f"{modelo['nombre']}.glb"
    return archivo if archivo.is_file() else None


_candados: dict[str, asyncio.Lock] = {}


async def asegurar(modelo_id: str) -> Path:
    """El archivo del modelo, descargando su kit si aún no está."""
    modelo = ficha(modelo_id)
    if modelo is None:
        raise BibliotecaError(
            f"«{modelo_id}» no está en la biblioteca: búscalo con estudio_biblioteca"
        )
    existente = ruta(modelo_id)
    if existente:
        return existente
    if modelo["kit"] not in KITS:
        raise BibliotecaError(f"Falta el archivo de «{modelo_id}»: vuelve a importarlo")
    candado = _candados.setdefault(modelo["kit"], asyncio.Lock())
    async with candado:
        existente = ruta(modelo_id)
        if existente:
            return existente
        contenido = await _descargar(modelo["kit"])
        await asyncio.to_thread(instalar, modelo["kit"], contenido)
    instalado = ruta(modelo_id)
    if instalado is None:
        raise BibliotecaError(f"El kit {modelo['kit']} se instaló sin «{modelo['nombre']}»")
    return instalado


async def _descargar(kit: str) -> bytes:
    """El zip del kit. Si el enlace guardado caducó, se busca en su página."""
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as cliente:
        try:
            respuesta = await cliente.get(KITS[kit]["url"])
            if respuesta.status_code == 404:
                pagina = await cliente.get(f"https://kenney.nl/assets/{kit}")
                enlace = re.search(
                    r"https://kenney\.nl/media/pages/assets/[^\"']+\.zip", pagina.text
                )
                if not enlace:
                    raise BibliotecaError(f"No se encuentra la descarga del kit {kit}")
                respuesta = await cliente.get(enlace.group(0))
            respuesta.raise_for_status()
        except httpx.HTTPError as error:
            raise BibliotecaError(
                f"No se pudo descargar el kit {kit} ({error.__class__.__name__}): "
                "sin red la biblioteca solo tiene lo ya descargado. Dilo y usa formas "
                "de estudio_objeto"
            ) from error
    if len(respuesta.content) > MAX_ZIP:
        raise BibliotecaError(f"El kit {kit} pesa más de lo esperado")
    return respuesta.content


def instalar(kit: str, contenido: bytes) -> list[dict]:
    """Saca los .glb del zip, les mete las texturas y los deja en la carpeta.

    Devuelve las fichas de índice de lo instalado (lo usa el script que
    regenera el índice).
    """
    destino = carpeta() / kit
    destino.mkdir(parents=True, exist_ok=True)
    fichas = []
    with zipfile.ZipFile(io.BytesIO(contenido)) as zip_:
        nombres = set(zip_.namelist())
        for nombre in sorted(nombres):
            partes = nombre.split("/")
            if (
                not nombre.endswith(".glb")
                or len(partes) < 3
                or partes[-3] != "Models"
                or partes[-2] not in ("GLB format", "GLTF format")
            ):
                continue
            base = posixpath.basename(nombre)[:-4]
            if not ID_VALIDO.match(f"{kit}/{base}"):
                continue
            directorio = posixpath.dirname(nombre)

            def leer(uri: str, directorio=directorio) -> bytes | None:
                completo = posixpath.normpath(posixpath.join(directorio, uri))
                return zip_.read(completo) if completo in nombres else None

            glb = empaquetar(zip_.read(nombre), leer)
            temporal = destino / f"{base}.glb.tmp"
            temporal.write_bytes(glb)
            temporal.replace(destino / f"{base}.glb")
            fichas.append(describir(kit, base, glb))
    return fichas


# --- glTF binario, lo justo -----------------------------------------------------


def _leer_glb(glb: bytes) -> tuple[dict, bytes]:
    magia, _, total = struct.unpack_from("<4sII", glb, 0)
    if magia != b"glTF":
        raise BibliotecaError("No es un glTF binario")
    desplazamiento, gltf, binario = 12, None, b""
    while desplazamiento < total:
        largo, tipo = struct.unpack_from("<I4s", glb, desplazamiento)
        trozo = glb[desplazamiento + 8 : desplazamiento + 8 + largo]
        if tipo == b"JSON":
            gltf = json.loads(trozo)
        elif tipo == b"BIN\x00":
            binario = trozo
        desplazamiento += 8 + largo
    if gltf is None:
        raise BibliotecaError("glTF sin JSON")
    return gltf, binario


def _escribir_glb(gltf: dict, binario: bytes) -> bytes:
    texto = json.dumps(gltf, separators=(",", ":")).encode()
    texto += b" " * (-len(texto) % 4)
    binario += b"\x00" * (-len(binario) % 4)
    trozos = struct.pack("<I4s", len(texto), b"JSON") + texto
    if binario:
        trozos += struct.pack("<I4s", len(binario), b"BIN\x00") + binario
    return struct.pack("<4sII", b"glTF", 2, 12 + len(trozos)) + trozos


def empaquetar(glb: bytes, leer) -> bytes:
    """Mete en el .glb las imágenes que referencia por `uri` (un archivo, no dos)."""
    gltf, binario = _leer_glb(glb)
    imagenes = [i for i in gltf.get("images", []) if "uri" in i]
    if not imagenes:
        return glb
    binario = bytearray(binario)
    vistas = gltf.setdefault("bufferViews", [])
    for imagen in imagenes:
        uri = imagen["uri"]
        if uri.startswith("data:"):
            continue
        datos = leer(uri)
        if datos is None:
            # Sin la textura se ve en blanco, pero se ve: mejor que nada.
            del imagen["uri"]
            continue
        binario += b"\x00" * (-len(binario) % 4)
        vistas.append({"buffer": 0, "byteOffset": len(binario), "byteLength": len(datos)})
        binario += datos
        del imagen["uri"]
        imagen["bufferView"] = len(vistas) - 1
        imagen["mimeType"] = "image/jpeg" if uri.lower().endswith((".jpg", ".jpeg")) else "image/png"
    buffers = gltf.setdefault("buffers", [{}])
    buffers[0] = {"byteLength": len(binario)}
    return _escribir_glb(gltf, bytes(binario))


def _matriz(nodo: dict) -> list[float]:
    """La matriz local (columna mayor, como glTF) de un nodo."""
    if "matrix" in nodo:
        return list(nodo["matrix"])
    tx, ty, tz = nodo.get("translation", [0, 0, 0])
    x, y, z, w = nodo.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = nodo.get("scale", [1, 1, 1])
    return [
        (1 - 2 * (y * y + z * z)) * sx, (2 * (x * y + z * w)) * sx, (2 * (x * z - y * w)) * sx, 0,
        (2 * (x * y - z * w)) * sy, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z + x * w)) * sy, 0,
        (2 * (x * z + y * w)) * sz, (2 * (y * z - x * w)) * sz, (1 - 2 * (x * x + y * y)) * sz, 0,
        tx, ty, tz, 1,
    ]


def _por(a: list[float], b: list[float]) -> list[float]:
    return [
        sum(a[k * 4 + fila] * b[columna * 4 + k] for k in range(4))
        for columna in range(4)
        for fila in range(4)
    ]


def _aplicar(m: list[float], p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


def describir(kit: str, nombre: str, glb: bytes) -> dict:
    """Ficha de índice: medidas reales (caja envolvente) y partes con nombre."""
    gltf, _ = _leer_glb(glb)
    nodos = gltf.get("nodes", [])
    escena = gltf.get("scenes", [{}])[gltf.get("scene", 0)] if gltf.get("scenes") else {}
    raices = escena.get("nodes", list(range(len(nodos))))
    minimo = [math.inf] * 3
    maximo = [-math.inf] * 3
    partes: list[str] = []

    def recorrer(indice_nodo: int, padre: list[float], profundidad: int) -> None:
        nodo = nodos[indice_nodo]
        mundo = _por(padre, _matriz(nodo))
        if "mesh" in nodo:
            for primitiva in gltf["meshes"][nodo["mesh"]]["primitives"]:
                accesor = gltf["accessors"][primitiva["attributes"]["POSITION"]]
                lo, hi = accesor.get("min"), accesor.get("max")
                if not lo or not hi:
                    continue
                for esquina in (
                    (x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])
                ):
                    punto = _aplicar(mundo, esquina)
                    for i in range(3):
                        minimo[i] = min(minimo[i], punto[i])
                        maximo[i] = max(maximo[i], punto[i])
        nombre_nodo = nodo.get("name")
        # Partes: los nodos con nombre propio por debajo de la raíz del modelo
        # (las ruedas, la carrocería). «Group» y similares no dicen nada.
        es_parte = (
            bool(nombre_nodo)
            and nombre_nodo not in ("Group", "tmpParent", nombre)
            and (profundidad > 0 or len(raices) > 1)
        )
        if es_parte and nombre_nodo not in partes:
            partes.append(nombre_nodo)
        for hijo in nodo.get("children", []):
            recorrer(hijo, mundo, profundidad + 1)

    identidad = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    for raiz in raices:
        recorrer(raiz, identidad, 0)
    if not math.isfinite(minimo[0]):
        minimo, maximo = [0.0] * 3, [0.0] * 3
    medidas = [round(maximo[i] - minimo[i], 3) for i in range(3)]
    return {
        "id": f"{kit}/{nombre}",
        "kit": kit,
        "nombre": nombre,
        "medidas": medidas,
        "partes": partes,
    }

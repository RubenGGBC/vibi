"""Objetos articulados descritos en URDF (PartNet-Mobility y parecidos) → .glb.

PartNet-Mobility (SAPIEN) tiene unos 2.300 objetos de casa con sus
articulaciones anotadas a mano: puertas, cajones, tapas, portátiles, grifos,
tijeras. Cada objeto es una carpeta con `mobility.urdf` (las piezas y cómo se
mueven), las mallas en `.obj` y, a veces, `semantics.txt` (qué es cada pieza)
y `meta.json` (la categoría).

La conversión deja cada articulación en un nodo propio del .glb:

- con el **pivote** en el origen de la articulación (la bisagra), y
- **girado** para que su eje sea el `y` local del nodo,

así que en Estudio abrir una puerta es girar ese nodo en `y`, y deslizar un
cajón es moverlo en `y`, igual que con las piezas de Kenney. Las mallas no se
mueven: el nodo de la pieza las compensa con el giro inverso.

Solo Python: los `.obj` se leen a mano (posiciones, coordenadas de textura,
normales, materiales con color y textura).
"""
from __future__ import annotations

import json
import math
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from . import biblioteca


class URDFError(ValueError):
    """El URDF o sus mallas no se pueden convertir. El mensaje dice por qué."""


MAX_VERTICES = 600_000

# --- Cuaterniones (x, y, z, w), como glTF ---------------------------------------


def _de_rpy(r: float, p: float, y: float) -> tuple[float, float, float, float]:
    """URDF: giro fijo en x (roll), luego y (pitch), luego z (yaw)."""
    cr, sr = math.cos(r / 2), math.sin(r / 2)
    cp, sp = math.cos(p / 2), math.sin(p / 2)
    cy, sy = math.cos(y / 2), math.sin(y / 2)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def _por(a: tuple, b: tuple) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _inverso(q: tuple) -> tuple[float, float, float, float]:
    x, y, z, w = q
    return (-x, -y, -z, w)


def _alinear_con_y(eje: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """El giro que lleva el `y` local al eje dado."""
    largo = math.sqrt(sum(c * c for c in eje)) or 1.0
    x, y, z = (c / largo for c in eje)
    # De (0, 1, 0) a (x, y, z): eje de giro = y × v, ángulo = acos(y · v).
    if y > 1 - 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    if y < -1 + 1e-9:
        return (1.0, 0.0, 0.0, 0.0)  # media vuelta en x
    cx, cy, cz = z, 0.0, -x
    s = math.sqrt(cx * cx + cz * cz)
    angulo = math.acos(max(-1.0, min(1.0, y)))
    k = math.sin(angulo / 2) / s
    return (cx * k, cy * k, cz * k, math.cos(angulo / 2))


def _limpio(q: tuple) -> list[float]:
    return [round(c, 7) for c in q]


# --- .obj y .mtl ---------------------------------------------------------------


def _leer_mtl(ruta: Path) -> dict[str, dict]:
    materiales: dict[str, dict] = {}
    actual = None
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        partes = linea.strip().split(maxsplit=1)
        if not partes:
            continue
        clave, resto = partes[0], (partes[1] if len(partes) > 1 else "")
        if clave == "newmtl":
            actual = materiales.setdefault(resto.strip(), {"color": [0.8, 0.8, 0.8], "opacidad": 1.0})
        elif actual is None:
            continue
        elif clave == "Kd":
            actual["color"] = [float(v) for v in resto.split()[:3]]
        elif clave == "d":
            actual["opacidad"] = float(resto.split()[0])
        elif clave == "map_Kd":
            # Las opciones (-s 1 1 1) van delante; el archivo, al final.
            actual["textura"] = (ruta.parent / resto.split()[-1]).resolve()
    return materiales


def leer_obj(ruta: Path) -> list[dict]:
    """Las mallas del .obj, una por material: posiciones, uv, normales, índices."""
    posiciones: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normales: list[tuple[float, float, float]] = []
    materiales: dict[str, dict] = {}
    grupos: dict[str, list[tuple]] = {}
    material = ""
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        partes = linea.split()
        if not partes:
            continue
        clave = partes[0]
        if clave == "v":
            posiciones.append(tuple(float(v) for v in partes[1:4]))
        elif clave == "vt":
            uvs.append((float(partes[1]), float(partes[2]) if len(partes) > 2 else 0.0))
        elif clave == "vn":
            normales.append(tuple(float(v) for v in partes[1:4]))
        elif clave == "usemtl":
            material = " ".join(partes[1:])
        elif clave == "mtllib":
            mtl = ruta.parent / " ".join(partes[1:])
            if mtl.is_file():
                materiales.update(_leer_mtl(mtl))
        elif clave == "f":
            esquinas = []
            for vertice in partes[1:]:
                indices = (vertice.split("/") + ["", ""])[:3]

                def indice(texto: str, total: int) -> int | None:
                    if not texto:
                        return None
                    n = int(texto)
                    return n - 1 if n > 0 else total + n

                esquinas.append((
                    indice(indices[0], len(posiciones)),
                    indice(indices[1], len(uvs)),
                    indice(indices[2], len(normales)),
                ))
            # Polígonos en abanico: (0, i, i + 1).
            for i in range(1, len(esquinas) - 1):
                grupos.setdefault(material, []).append((esquinas[0], esquinas[i], esquinas[i + 1]))
    mallas = []
    for nombre, triangulos in grupos.items():
        vistos: dict[tuple, int] = {}
        pos, uv, nor, indices = [], [], [], []
        tiene_uv = all(e[1] is not None for t in triangulos for e in t)
        tiene_normal = all(e[2] is not None for t in triangulos for e in t)
        for triangulo in triangulos:
            if not tiene_normal:
                # Sin normales: la de la cara, para que la luz no lo deje negro.
                a, b, c = (posiciones[e[0]] for e in triangulo)
                u = [b[i] - a[i] for i in range(3)]
                v = [c[i] - a[i] for i in range(3)]
                n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                largo = math.sqrt(sum(x * x for x in n)) or 1.0
                cara = tuple(x / largo for x in n)
            for esquina in triangulo:
                clave = esquina if tiene_normal else (*esquina[:2], triangulo)
                if clave not in vistos:
                    vistos[clave] = len(pos)
                    pos.append(posiciones[esquina[0]])
                    if tiene_uv:
                        uv.append(uvs[esquina[1]])
                    nor.append(normales[esquina[2]] if tiene_normal else cara)
                indices.append(vistos[clave])
        mallas.append({
            "posiciones": pos, "uvs": uv if tiene_uv else None, "normales": nor,
            "indices": indices, "material": materiales.get(nombre, {"color": [0.8, 0.8, 0.8], "opacidad": 1.0}),
        })
    return mallas


# --- El .glb -------------------------------------------------------------------


class _Constructor:
    """Acumula nodos, mallas, materiales y el búfer binario de un glTF."""

    def __init__(self) -> None:
        self.gltf: dict = {
            "asset": {"version": "2.0", "generator": "Vibi Estudio (URDF)"},
            "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
            "materials": [], "accessors": [], "bufferViews": [], "buffers": [],
        }
        self.binario = bytearray()
        self.texturas: dict[Path, int] = {}
        self.vertices = 0

    def _vista(self, datos: bytes, objetivo: int | None = None) -> int:
        while len(self.binario) % 4:
            self.binario.append(0)
        vista = {"buffer": 0, "byteOffset": len(self.binario), "byteLength": len(datos)}
        if objetivo:
            vista["target"] = objetivo
        self.binario.extend(datos)
        self.gltf["bufferViews"].append(vista)
        return len(self.gltf["bufferViews"]) - 1

    def _accesor(self, valores: list, tipo: str, componentes: int, con_limites: bool = False) -> int:
        plano = [c for v in valores for c in v] if componentes > 1 else list(valores)
        if tipo == "indices":
            datos = struct.pack(f"<{len(plano)}I", *plano)
            accesor = {"componentType": 5125, "type": "SCALAR",
                       "bufferView": self._vista(datos, 34963)}
        else:
            datos = struct.pack(f"<{len(plano)}f", *plano)
            accesor = {"componentType": 5126, "type": {2: "VEC2", 3: "VEC3"}[componentes],
                       "bufferView": self._vista(datos, 34962)}
        accesor["count"] = len(valores)
        if con_limites:
            accesor["min"] = [min(v[i] for v in valores) for i in range(componentes)]
            accesor["max"] = [max(v[i] for v in valores) for i in range(componentes)]
        self.gltf["accessors"].append(accesor)
        return len(self.gltf["accessors"]) - 1

    def _material(self, material: dict) -> int:
        r, g, b = material["color"]
        pbr = {"baseColorFactor": [r, g, b, material["opacidad"]], "metallicFactor": 0.0, "roughnessFactor": 0.75}
        textura = material.get("textura")
        if textura and textura.is_file():
            if textura not in self.texturas:
                tipo = "image/png" if textura.suffix.lower() == ".png" else "image/jpeg"
                self.gltf.setdefault("images", []).append(
                    {"bufferView": self._vista(textura.read_bytes()), "mimeType": tipo}
                )
                self.gltf.setdefault("textures", []).append({"source": len(self.gltf["images"]) - 1})
                self.texturas[textura] = len(self.gltf["textures"]) - 1
            pbr["baseColorTexture"] = {"index": self.texturas[textura]}
            pbr["baseColorFactor"] = [1.0, 1.0, 1.0, material["opacidad"]]
        nuevo = {"pbrMetallicRoughness": pbr, "doubleSided": True}
        if material["opacidad"] < 1:
            nuevo["alphaMode"] = "BLEND"
        self.gltf["materials"].append(nuevo)
        return len(self.gltf["materials"]) - 1

    def malla(self, mallas: list[dict]) -> int | None:
        primitivas = []
        for m in mallas:
            if not m["indices"]:
                continue
            self.vertices += len(m["posiciones"])
            if self.vertices > MAX_VERTICES:
                raise URDFError(f"Demasiada geometría (más de {MAX_VERTICES} vértices)")
            atributos = {
                "POSITION": self._accesor(m["posiciones"], "f", 3, con_limites=True),
                "NORMAL": self._accesor(m["normales"], "f", 3),
            }
            if m["uvs"]:
                # .obj cuenta la v desde abajo; glTF, desde arriba.
                atributos["TEXCOORD_0"] = self._accesor([(u, 1 - v) for u, v in m["uvs"]], "f", 2)
            primitivas.append({
                "attributes": atributos,
                "indices": self._accesor(m["indices"], "indices", 1),
                "material": self._material(m["material"]),
            })
        if not primitivas:
            return None
        self.gltf["meshes"].append({"primitives": primitivas})
        return len(self.gltf["meshes"]) - 1

    def nodo(self, padre: int | None, **datos) -> int:
        self.gltf["nodes"].append({k: v for k, v in datos.items() if v is not None})
        indice = len(self.gltf["nodes"]) - 1
        if padre is None:
            self.gltf["scenes"][0]["nodes"].append(indice)
        else:
            self.gltf["nodes"][padre].setdefault("children", []).append(indice)
        return indice

    def glb(self) -> bytes:
        self.gltf["buffers"] = [{"byteLength": len(self.binario)}]
        for clave in ("materials", "accessors", "bufferViews", "meshes"):
            if not self.gltf[clave]:
                del self.gltf[clave]
        return biblioteca._escribir_glb(self.gltf, bytes(self.binario))


# --- URDF ------------------------------------------------------------------------


def _numeros(texto: str | None, defecto: tuple) -> tuple:
    return tuple(float(v) for v in texto.split()) if texto else defecto


def _origen(elemento: ET.Element | None) -> tuple[tuple, tuple]:
    if elemento is None:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return _numeros(elemento.get("xyz"), (0.0, 0.0, 0.0)), _numeros(elemento.get("rpy"), (0.0, 0.0, 0.0))


def _semantica(carpeta: Path) -> dict[str, str]:
    """`semantics.txt` de PartNet-Mobility: «link_1 hinge door» → link_1: door."""
    archivo = carpeta / "semantics.txt"
    if not archivo.is_file():
        return {}
    nombres = {}
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        partes = linea.split()
        if len(partes) >= 3:
            nombres[partes[0]] = partes[2]
    return nombres


def convertir(carpeta: Path, z_arriba: bool = False) -> tuple[bytes, list[dict], str]:
    """El .glb, las articulaciones que tiene y un título para buscarlo.

    Las articulaciones salen con su pieza (el nodo de la articulación), tipo,
    eje `y` y topes: grados en los giros, unidades del archivo en los
    deslizamientos.
    """
    urdf = carpeta / "mobility.urdf"
    if not urdf.is_file():
        candidatos = sorted(carpeta.glob("*.urdf"))
        if not candidatos:
            raise URDFError(f"No hay ningún .urdf en {carpeta}")
        urdf = candidatos[0]
    try:
        raiz_xml = ET.parse(urdf).getroot()
    except ET.ParseError as error:
        raise URDFError(f"{urdf.name} no es XML válido: {error}") from error
    enlaces = {e.get("name"): e for e in raiz_xml.findall("link")}
    juntas = raiz_xml.findall("joint")
    hijos = {j.find("child").get("link") for j in juntas if j.find("child") is not None}
    raices = [n for n in enlaces if n not in hijos]
    if len(raices) != 1:
        raise URDFError(f"El URDF tiene que tener una sola pieza raíz; tiene {raices}")
    semantica = _semantica(carpeta)
    constructor = _Constructor()
    articulaciones: list[dict] = []
    usados: dict[str, int] = {}

    def nombre_de(enlace: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", semantica.get(enlace, enlace)).strip("_") or "pieza"
        usados[base] = usados.get(base, 0) + 1
        return base if usados[base] == 1 else f"{base}_{usados[base]}"

    def colgar_enlace(nombre: str, padre: int) -> None:
        enlace = enlaces[nombre]
        for visual in enlace.findall("visual"):
            malla = visual.find("geometry/mesh")
            if malla is None or not malla.get("filename"):
                continue
            archivo = (carpeta / malla.get("filename").replace("package://", "")).resolve()
            if not archivo.is_relative_to(carpeta.resolve()):
                raise URDFError(f"Una malla apunta fuera de la carpeta: {malla.get('filename')}")
            if archivo.suffix.lower() != ".obj" or not archivo.is_file():
                raise URDFError(f"Solo se leen mallas .obj; falta o no es .obj: {archivo.name}")
            indice = constructor.malla(leer_obj(archivo))
            if indice is None:
                continue
            xyz, rpy = _origen(visual.find("origin"))
            escala = _numeros(malla.get("scale"), (1.0, 1.0, 1.0))
            constructor.nodo(
                padre, mesh=indice, translation=list(xyz), rotation=_limpio(_de_rpy(*rpy)),
                scale=list(escala) if escala != (1.0, 1.0, 1.0) else None,
            )
        for junta in juntas:
            if junta.find("parent").get("link") != nombre:
                continue
            hijo = junta.find("child").get("link")
            xyz, rpy = _origen(junta.find("origin"))
            tipo = junta.get("type", "fixed")
            eje = _numeros(junta.find("axis").get("xyz") if junta.find("axis") is not None else None, (1.0, 0.0, 0.0))
            alinear = _alinear_con_y(eje) if tipo != "fixed" else (0.0, 0.0, 0.0, 1.0)
            pieza = nombre_de(hijo)
            # El nodo de la articulación: pivote en su origen, eje en su `y`.
            nodo_junta = constructor.nodo(
                padre, name=pieza, translation=list(xyz), rotation=_limpio(_por(_de_rpy(*rpy), alinear)),
            )
            # Y la pieza, con el giro inverso: las mallas quedan donde estaban.
            nodo_hijo = constructor.nodo(nodo_junta, rotation=_limpio(_inverso(alinear)))
            colgar_enlace(hijo, nodo_hijo)
            if tipo in ("revolute", "continuous", "prismatic"):
                limite = junta.find("limit")
                articulacion = {"partes": [pieza], "tipo": "desliza" if tipo == "prismatic" else "giro", "eje": "y"}
                if tipo != "continuous" and limite is not None and limite.get("lower") is not None:
                    bajo, alto = float(limite.get("lower")), float(limite.get("upper", 0))
                    decimales = 4
                    if tipo == "revolute":
                        bajo, alto, decimales = math.degrees(bajo), math.degrees(alto), 1
                    if bajo < alto:
                        articulacion["minimo"] = round(bajo, decimales)
                        articulacion["maximo"] = round(alto, decimales)
                articulaciones.append(articulacion)

    # URDF suele ir con z hacia arriba; Estudio, como glTF, con y.
    giro_raiz = _limpio(_de_rpy(-math.pi / 2, 0, 0)) if z_arriba else None
    raiz = constructor.nodo(None, name=carpeta.name, rotation=giro_raiz)
    colgar_enlace(raices[0], raiz)
    if not constructor.gltf["meshes"]:
        raise URDFError("El URDF no tiene ninguna malla que pintar")
    categoria = ""
    meta = carpeta / "meta.json"
    if meta.is_file():
        try:
            categoria = json.loads(meta.read_text(encoding="utf-8")).get("model_cat", "")
        except (OSError, json.JSONDecodeError):
            pass
    piezas = sorted({a["partes"][0].rstrip("_0123456789") for a in articulaciones})
    titulo = " ".join(p for p in (categoria or carpeta.name, f"({', '.join(piezas)})" if piezas else "") if p)
    return constructor.glb(), articulaciones, titulo


def importar(carpeta: Path, kit: str = "partnet", z_arriba: bool = False) -> dict:
    """Convierte la carpeta y la deja en la biblioteca como un modelo más."""
    nombre = re.sub(r"[^A-Za-z0-9_.-]+", "-", carpeta.name)[:80]
    glb, articulaciones, titulo = convertir(carpeta, z_arriba=z_arriba)
    ficha = biblioteca.describir(kit, nombre, glb)
    ficha.update({
        "titulo": titulo[:80],
        "autor": "SAPIEN (UC San Diego)" if kit == "partnet" else carpeta.name,
        "licencia": "uso académico (términos de PartNet-Mobility)" if kit == "partnet" else "la del URDF",
        "plataforma": "PartNet-Mobility" if kit == "partnet" else "URDF",
        "articulaciones_sugeridas": articulaciones,
    })
    if kit == "partnet":
        ficha["pagina"] = "https://sapien.ucsd.edu/browse"
    return biblioteca.registrar_externo(ficha, glb)

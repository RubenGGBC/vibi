"""Extrae piezas del atlas Z-Anatomy a un .glb, una malla por pieza.

Lo lanza Vibi en un subproceso (`app/estudio/atlas.py`) con el Python que
tenga Blender como módulo (`pip install bpy`, Python 3.11):

    python scripts/estudio_exportar_atlas.py -- Startup.blend piezas.json salida.glb

`piezas.json` es una lista de nombres exactos del índice. Las curvas (vasos,
nervios) se convierten en malla y cada pieza recibe un color plano según su
sistema, como en un atlas impreso: hueso marfil, músculo rojo, arterias rojas,
venas azules, nervios amarillos.
"""
import json
import sys

import bpy

entrada, lista, salida = sys.argv[-3], sys.argv[-2], sys.argv[-1]
with open(lista, encoding="utf-8") as f:
    PIEZAS = json.load(f)
bpy.ops.wm.open_mainfile(filepath=entrada)


def color(objeto):
    n = objeto.name.lower()
    colecciones = " ".join(c.name.lower() for c in objeto.users_collection)
    if "leaflet" in n or "cartilage" in n or "meniscus" in n or "disc" in n:
        return (0.93, 0.86, 0.68)
    if "skeletal" in colecciones:
        return (0.90, 0.86, 0.76)
    if "joints" in colecciones or "ligament" in n:
        return (0.74, 0.82, 0.88)
    if "insertions" in colecciones or "tendon" in n or "aponeurosis" in n:
        return (0.86, 0.80, 0.70)
    if "muscular" in colecciones or "papillary" in n:
        return (0.66, 0.20, 0.20)
    if "cardiovascular" in colecciones:
        if "heart" in colecciones and "vein" not in n and "artery" not in n:
            return (0.62, 0.18, 0.20)
        venoso = any(p in n for p in ("vein", "vena", "sinus", "plexus", "pulmonary trunk"))
        if venoso and "pulmonary vein" not in n:
            return (0.17, 0.32, 0.72)
        return (0.80, 0.12, 0.14)
    if "nervous" in colecciones:
        if "nerve" in n or "plexus" in n or "ganglion" in n or "trunk" in n:
            return (0.95, 0.78, 0.28)
        return (0.86, 0.72, 0.72)
    if "lymphoid" in colecciones:
        return (0.42, 0.70, 0.45)
    if "visceral" in colecciones:
        if "lung" in n or "bronch" in n:
            return (0.90, 0.62, 0.62)
        if "liver" in n or "kidney" in n or "spleen" in n:
            return (0.55, 0.22, 0.18)
        return (0.80, 0.52, 0.45)
    return (0.85, 0.72, 0.64)


materiales = {}


def material(rgb):
    if rgb not in materiales:
        m = bpy.data.materials.new(f"Estudio {rgb}")
        m.use_nodes = True
        bsdf = m.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.55
        materiales[rgb] = m
    return materiales[rgb]


grafo = bpy.context.evaluated_depsgraph_get()
destino = bpy.data.collections.new("Exportar")
bpy.context.scene.collection.children.link(destino)
nuevos = []
for nombre in PIEZAS:
    original = bpy.data.objects.get(nombre)
    if original is None or original.type not in ("MESH", "CURVE"):
        print("FALTA", nombre)
        continue
    malla = bpy.data.meshes.new_from_object(original.evaluated_get(grafo))
    rgb = color(original)
    original.name = nombre + "__atlas"
    malla.materials.clear()
    malla.materials.append(material(rgb))
    copia = bpy.data.objects.new(nombre, malla)
    copia.matrix_world = original.matrix_world.copy()
    destino.objects.link(copia)
    nuevos.append(copia)
if not nuevos:
    print("NADA")
    sys.exit(2)
bpy.ops.object.select_all(action="DESELECT")
for o in nuevos:
    o.select_set(True)
bpy.context.view_layer.objects.active = nuevos[0]
bpy.ops.export_scene.gltf(filepath=salida, export_format="GLB", use_selection=True, export_yup=True)
print("EXPORTADO", len(nuevos))

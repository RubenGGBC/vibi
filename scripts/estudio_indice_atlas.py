"""Construye el índice de estructuras del atlas Z-Anatomy (sin geometría).

Uso (Blender como módulo, Python 3.11):

    python scripts/estudio_indice_atlas.py -- Startup.blend app/estudio/atlas/indice.json

El índice es lo que consulta `estudio.atlas_buscar`: nombre de cada pieza con
geometría, su sistema (esquelético, muscular…), los grupos en los que está y
su número de vértices. Se versiona en el repo; la geometría no, que se extrae
bajo demanda.
"""
import json
import re
import sys

import bpy

entrada, salida = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=entrada)
SISTEMA = re.compile(r"^\d+: ")
estructuras = []
for o in bpy.data.objects:
    if o.type == "MESH":
        vertices = len(o.data.vertices)
        if vertices <= 2:  # las «.j» son anclas de etiquetas, no piezas
            continue
    elif o.type == "CURVE":
        if not (o.data.bevel_depth > 0 or o.data.bevel_object or o.modifiers):
            continue
        vertices = sum(len(s.points) + len(s.bezier_points) for s in o.data.splines) * 16
    else:
        continue
    colecciones = [c.name for c in o.users_collection]
    sistema = next((c for c in colecciones if SISTEMA.match(c)), "")
    estructuras.append(
        {
            "nombre": o.name,
            "sistema": SISTEMA.sub("", sistema),
            "grupos": sorted(c for c in colecciones if not SISTEMA.match(c)),
            "vertices": vertices,
        }
    )
estructuras.sort(key=lambda e: e["nombre"])
with open(salida, "w", encoding="utf-8") as f:
    json.dump(
        {
            "fuente": "Z-Anatomy (derivado de BodyParts3D), CC BY-SA 4.0",
            "estructuras": estructuras,
        },
        f,
        ensure_ascii=False,
        separators=(",", ":"),
    )
print("ESTRUCTURAS", len(estructuras))

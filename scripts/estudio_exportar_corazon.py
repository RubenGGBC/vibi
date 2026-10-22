"""Extrae el corazón del atlas Z-Anatomy a un .glb, una malla por pieza.

Uso (Blender como módulo de Python, `pip install bpy`, que pide Python 3.11):

    python scripts/estudio_exportar_corazon.py -- Startup.blend corazon.glb

`Startup.blend` está dentro de `Z-Anatomy.zip` en
https://github.com/Z-Anatomy/Models-of-human-anatomy (CC BY-SA 4.0).
El resultado va a `app/estudio/modelos_incluidos/` o a `data/estudio/modelos/`.
"""
import bpy, sys
entrada, salida = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=entrada)
PIEZAS = [o.name for o in bpy.data.collections["Heart"].all_objects if o.type == "MESH"] + [
    "Pulmonary trunk", "Ascending aorta", "Aortic arch", "Superior vena cava",
    "Inferior vena cava (thoracic part)", "Left superior pulmonary vein",
    "Left inferior pulmonary vein", "Right superior pulmonary vein",
    "Right inferior pulmonary vein", "Left coronary artery", "Right coronary artery",
]
# Colores de libro de texto: miocardio granate, arterias rojas, venas azules
# (el tronco pulmonar lleva sangre sin oxígeno: azul; las venas pulmonares,
# con oxígeno: rojo), válvulas claras.
def color(nombre):
    n = nombre.lower()
    if "leaflet" in n:
        return (0.93, 0.86, 0.68)
    if "papillary" in n:
        return (0.45, 0.10, 0.12)
    if "vena cava" in n or "pulmonary trunk" in n:
        return (0.17, 0.32, 0.72)
    if "pulmonary vein" in n or "aort" in n or "coronary artery" in n:
        return (0.80, 0.12, 0.14)
    return (0.62, 0.18, 0.20)

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
    original = bpy.data.objects[nombre]
    malla = bpy.data.meshes.new_from_object(original.evaluated_get(grafo), preserve_all_data_layers=False)
    original.name = nombre + "__atlas"
    malla.materials.clear()
    malla.materials.append(material(color(nombre)))
    copia = bpy.data.objects.new(nombre, malla)
    copia.matrix_world = original.matrix_world.copy()
    destino.objects.link(copia)
    nuevos.append(copia)
    print("PIEZA", nombre, len(malla.vertices), [m.name for m in malla.materials if m])
bpy.ops.object.select_all(action="DESELECT")
for o in nuevos:
    o.select_set(True)
bpy.context.view_layer.objects.active = nuevos[0]
bpy.ops.export_scene.gltf(filepath=salida, export_format="GLB", use_selection=True, export_yup=True, export_apply=False)
print("EXPORTADO", salida)

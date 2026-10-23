"""Importa objetos articulados en URDF (PartNet-Mobility) a la biblioteca de Estudio.

    .venv/bin/python scripts/estudio_importar_urdf.py <carpeta> [<carpeta> ...] [--z-arriba] [--kit urdf]

Cada carpeta es un objeto: `mobility.urdf` (o cualquier `.urdf`) con mallas
`.obj`; de PartNet-Mobility, además, `semantics.txt` y `meta.json`. Se baja de
https://sapien.ucsd.edu/downloads (pide cuenta y aceptar sus términos). El
objeto queda en `<datos>/estudio/biblioteca/` y el agente lo encuentra con
estudio_biblioteca por su categoría («StorageFurniture», «Laptop»…), con sus
puertas, tapas y cajones ya articulados.

PartNet-Mobility va con y hacia arriba; muchos URDF de robots, con z: para
esos, --z-arriba.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.estudio import urdf  # noqa: E402


def main() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("carpetas", nargs="+", type=Path)
    argumentos.add_argument("--z-arriba", action="store_true", help="el URDF tiene z hacia arriba")
    argumentos.add_argument("--kit", default="partnet", help="nombre de la colección (partnet, urdf…)")
    opciones = argumentos.parse_args()
    fallos = 0
    for carpeta in opciones.carpetas:
        try:
            ficha = urdf.importar(carpeta, kit=opciones.kit, z_arriba=opciones.z_arriba)
        except (urdf.URDFError, OSError) as error:
            print(f"{carpeta.name}: {error}", file=sys.stderr)
            fallos += 1
            continue
        articulaciones = ", ".join(
            f"{a['partes'][0]} ({a['tipo']})" for a in ficha["articulaciones_sugeridas"]
        )
        print(f"{ficha['id']}: «{ficha['titulo']}», {ficha['medidas']} — {articulaciones or 'sin articulaciones'}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

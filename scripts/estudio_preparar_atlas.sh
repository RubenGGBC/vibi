#!/usr/bin/env bash
# Deja listo el atlas anatómico de Estudio: el .blend de Z-Anatomy y un Python
# con Blender como módulo. Al final imprime las dos líneas para el .env.
#
#   scripts/estudio_preparar_atlas.sh [carpeta]   (por defecto data/estudio/atlas-fuente)
set -euo pipefail
DESTINO="${1:-data/estudio/atlas-fuente}"
mkdir -p "$DESTINO"

if [ ! -f "$DESTINO/Startup.blend" ]; then
  echo "Descargando Z-Anatomy (CC BY-SA 4.0)…"
  git clone -q --depth 1 --filter=blob:none --no-checkout \
    https://github.com/Z-Anatomy/Models-of-human-anatomy "$DESTINO/repo"
  git -C "$DESTINO/repo" checkout -q HEAD -- Z-Anatomy.zip
  python3 - "$DESTINO" <<'PY'
import sys, zipfile
destino = sys.argv[1]
zipfile.ZipFile(f"{destino}/repo/Z-Anatomy.zip").extract("Z-Anatomy/Startup.blend", destino)
PY
  mv "$DESTINO/Z-Anatomy/Startup.blend" "$DESTINO/Startup.blend"
  rm -rf "$DESTINO/repo" "$DESTINO/Z-Anatomy"
fi

# bpy (Blender como módulo) solo se publica para Python 3.11; uv lo trae.
command -v uv >/dev/null 2>&1 || python3 -m pip install --user uv
uv venv -q -p 3.11 "$DESTINO/blender-venv"
uv pip install -q -p "$DESTINO/blender-venv/bin/python" bpy

echo
echo "Añade al .env:"
echo "ESTUDIO_ATLAS_BLEND=$(realpath "$DESTINO/Startup.blend")"
echo "ESTUDIO_BLENDER_PYTHON=$(realpath "$DESTINO/blender-venv/bin/python")"

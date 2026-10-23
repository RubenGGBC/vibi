"""Descarga todos los kits de la biblioteca de Estudio y regenera su índice.

    .venv/bin/python scripts/estudio_preparar_biblioteca.py [kit ...]

Sin argumentos instala todos los de `biblioteca.KITS`. El índice
(`app/estudio/biblioteca/indice.json`) va versionado: se regenera solo cuando
cambia la lista de kits. Los .glb quedan en `<datos>/estudio/biblioteca/`; el
servidor también los descarga solo, bajo demanda, si faltan.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.estudio import biblioteca  # noqa: E402


async def main(pedidos: list[str]) -> None:
    kits = pedidos or list(biblioteca.KITS)
    desconocidos = [k for k in kits if k not in biblioteca.KITS]
    if desconocidos:
        raise SystemExit(f"Kits desconocidos: {', '.join(desconocidos)}")
    previo = {}
    if biblioteca.INDICE.is_file():
        previo = {m["id"]: m for m in json.loads(biblioteca.INDICE.read_text())["modelos"]}
    fichas = {i: m for i, m in previo.items() if m["kit"] not in kits}
    for kit in kits:
        print(f"{kit}: descargando…", flush=True)
        contenido = await biblioteca._descargar(kit)
        nuevas = biblioteca.instalar(kit, contenido)
        fichas.update({f["id"]: f for f in nuevas})
        print(f"{kit}: {len(nuevas)} modelos")
    biblioteca.INDICE.parent.mkdir(parents=True, exist_ok=True)
    datos = {
        "fuente": biblioteca.FUENTE,
        "modelos": sorted(fichas.values(), key=lambda m: m["id"]),
    }
    biblioteca.INDICE.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(f"Índice: {len(fichas)} modelos en {biblioteca.INDICE}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))

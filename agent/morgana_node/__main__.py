"""Agente de Morgana para una máquina propia.

    python -m morgana_node registrar --url https://mi-pc.mi-tailnet.ts.net
    python -m morgana_node                 # arranca y se queda conectado
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from pathlib import Path

import httpx

from . import config as node_config
from .client import run_forever
from .config import NodeConfig

log = logging.getLogger("morgana.node")


def _registrar(args: argparse.Namespace) -> int:
    base_url = args.url.rstrip("/")
    nombre_nodo = args.nombre or node_config.default_node_name()
    projects_root = Path(
        args.proyectos or node_config.default_projects_root()
    ).expanduser()
    inbox_root = Path(
        args.entrante or node_config.default_inbox_root()
    ).expanduser()

    print(f"Registrando «{nombre_nodo}» en {base_url}")
    usuario = args.usuario or input("Usuario de Morgana: ").strip()
    contraseña = getpass.getpass("Contraseña: ")

    try:
        response = httpx.post(
            f"{base_url}/api/auth/nodos",
            json={
                "nombre": usuario,
                "contraseña": contraseña,
                "nodo": nombre_nodo,
                "plataforma": node_config.platform_label(),
            },
            timeout=30,
        )
    except httpx.HTTPError as error:
        print(f"No se pudo contactar con Morgana: {error}", file=sys.stderr)
        return 1

    if response.status_code != 200:
        detalle = response.json().get("error", response.text)
        print(f"Alta rechazada: {detalle}", file=sys.stderr)
        return 1

    data = response.json()
    node_config.save(
        NodeConfig(
            url=base_url,
            node_id=data["nodo"]["id"],
            token=data["token"],
            nombre=data["nodo"]["nombre"],
            projects_root=str(projects_root),
            inbox_root=str(inbox_root),
        )
    )
    print(f"Listo. Credencial guardada en {node_config.CONFIG_PATH}")
    print(f"Proyectos que verá Morgana: {projects_root}")
    print(f"Los archivos que te manden caerán en: {inbox_root}")
    print("Arranca el agente con:  python -m morgana_node")
    return 0


def _arrancar(_: argparse.Namespace) -> int:
    try:
        config = node_config.load()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    if config is None:
        print(
            "Este equipo no está registrado todavía. Ejecuta:\n"
            "  python -m morgana_node registrar --url https://tu-morgana",
            file=sys.stderr,
        )
        return 1

    log.info("Nodo «%s» → %s", config.nombre, config.url)
    try:
        asyncio.run(run_forever(config))
    except KeyboardInterrupt:
        log.info("Agente detenido")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(prog="morgana_node", description=__doc__)
    subcommands = parser.add_subparsers(dest="comando")

    alta = subcommands.add_parser("registrar", help="Vincula este equipo")
    alta.add_argument("--url", required=True, help="URL de tu Morgana")
    alta.add_argument("--usuario", help="Usuario de Morgana (si no, se pregunta)")
    alta.add_argument("--nombre", help="Nombre del dispositivo (por defecto, el hostname)")
    alta.add_argument("--proyectos", help="Carpeta de proyectos que verá Morgana")
    alta.add_argument(
        "--entrante",
        help="Carpeta donde caerán los archivos que te manden (por defecto, "
        "~/Morgana/Entrante)",
    )
    alta.set_defaults(func=_registrar)

    args = parser.parse_args(argv)
    handler = getattr(args, "func", _arrancar)
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

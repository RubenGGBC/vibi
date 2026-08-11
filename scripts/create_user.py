"""Crea un usuario de Vibi desde la máquina principal.

Uso: python -m scripts.create_user ana [--admin]
"""
import argparse
import getpass

from app import auth, db


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nombre", help="Nombre único para iniciar sesión")
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Permite publicar herramientas para todo el laboratorio",
    )
    args = parser.parse_args()

    db.init_db()
    if db.get_user_by_nombre(args.nombre):
        parser.error(f"Ya existe el usuario {args.nombre!r}")
    password = getpass.getpass("Contraseña: ")
    confirmation = getpass.getpass("Repite la contraseña: ")
    if password != confirmation:
        parser.error("Las contraseñas no coinciden")

    user = db.get_or_create_user(args.nombre)
    db.set_password_hash(user["id"], auth.hash_password(password))
    db.set_user_admin(user["id"], args.admin)
    print(f"Usuario {args.nombre} creado ({user['id']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

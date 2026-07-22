"""Fija la contraseña de un usuario existente.

Uso: python -m scripts.set_password ruben
"""
import argparse
import getpass

from app import auth, db


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nombre", help="Nombre exacto del usuario existente")
    args = parser.parse_args()

    db.init_db()
    user = db.get_user_by_nombre(args.nombre)
    if not user:
        parser.error(f"No existe el usuario {args.nombre!r}")

    password = getpass.getpass("Nueva contraseña: ")
    confirmation = getpass.getpass("Repite la contraseña: ")
    if password != confirmation:
        parser.error("Las contraseñas no coinciden")

    db.set_password_hash(user["id"], auth.hash_password(password))
    print(f"Contraseña actualizada para {args.nombre}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Instala Vibi en este ordenador.

    python install.py                 instala o reconfigura
    python install.py --hay-novedades comprueba si hay versión nueva
    python install.py --actualizar    la trae y deja las dependencias al día

Sin argumentos abre un asistente en el navegador: comprueba qué hay en la
máquina, te deja elegir cuenta, modelo y qué quieres que Vibi sepa hacer aquí,
y lo deja todo en marcha.

Este archivo no importa nada de fuera de la biblioteca estándar, y no puede:
es lo primero que se ejecuta, antes de que exista el entorno donde viven las
dependencias. Por eso comprueba la versión de Python a mano en vez de fiarse
de que el resto del código cargue.
"""
from __future__ import annotations

import sys

MINIMO = (3, 11)


def main() -> int:
    # La consola de Windows viene en cp1252 y parte los acentos: lo primero que
    # se lee del instalador sería «Vibi se est� despertando». Se arregla aquí y
    # no en cada `print`, y con `errors` puesto para que una consola rara no
    # tumbe la instalación entera por un acento.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    if sys.version_info[:2] < MINIMO:
        minimo = ".".join(str(n) for n in MINIMO)
        actual = ".".join(str(n) for n in sys.version_info[:3])
        print(
            f"\n  Vibi necesita Python {minimo} o posterior, y este es el {actual}."
            f"\n  Instálalo desde python.org y vuelve a lanzar:"
            f"\n\n    python install.py\n",
            file=sys.stderr,
        )
        return 1

    if "--actualizar" in sys.argv:
        return _actualizar()
    if "--hay-novedades" in sys.argv:
        return _hay_novedades()

    return _abrir_ventana()


# La biblioteca con la que se dibuja la ventana. Se instala en el entorno de
# Vibi y no en el Python del sistema, que no se toca. Pesa alrededor de un mega:
# por dentro usa el WebView que ya trae el sistema operativo.
BIBLIOTECA_VENTANA = "pywebview"


def _abrir_ventana() -> int:
    """Prepara lo justo para poder dibujar, y abre.

    Es lo único que pasa por consola, y dura unos segundos la primera vez. No
    hay forma de evitarlo del todo: la ventana necesita una biblioteca, y una
    biblioteca necesita un sitio donde vivir. A cambio, el Python del sistema
    se queda como estaba.
    """
    import subprocess  # noqa: PLC0415

    from installer import acciones, deteccion  # noqa: PLC0415

    raiz = deteccion.raiz_del_repo()
    python = acciones.python_del_entorno(raiz)

    if not python.exists():
        print("  Preparando el instalador…", flush=True)
        try:
            acciones.crear_entorno(raiz)
        except subprocess.CalledProcessError as error:
            print(f"\n  No he podido crear el entorno: {error}\n", file=sys.stderr)
            return 2

    if not _tiene_ventana(python):
        print("  Un momento, que traigo lo que necesito para la ventana…", flush=True)
        hecho = subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--quiet",
                BIBLIOTECA_VENTANA,
            ],
            check=False,
        )
        if hecho.returncode != 0:
            print(
                "\n  No he podido preparar la ventana. Comprueba tu conexión y"
                "\n  vuelve a lanzar:  python install.py\n",
                file=sys.stderr,
            )
            return 2

    return subprocess.run([str(python), "-m", "installer"], cwd=str(raiz)).returncode


def _tiene_ventana(python) -> bool:
    import subprocess  # noqa: PLC0415

    hecho = subprocess.run(
        [str(python), "-c", "import webview"],
        capture_output=True,
        check=False,
    )
    return hecho.returncode == 0


def _hay_novedades() -> int:
    """Dice si hay versión nueva sin traerla.

    Sale 0 si la hay, 1 si estás al día y 2 si no se ha podido comprobar. El
    código de salida es para encadenarlo desde un guion; el texto, para leerlo
    de un vistazo.
    """
    from installer import actualizacion  # noqa: PLC0415

    novedades = actualizacion.novedades()
    if novedades.problema:
        print(f"\n  No he podido comprobarlo: {novedades.problema}\n", file=sys.stderr)
        return 2
    if not novedades.hay:
        print("\n  Vibi ya está al día.\n")
        return 1
    print(f"\n  Hay {novedades.commits} cambios nuevos:\n")
    for titulo in novedades.titulos:
        print(f"    · {titulo}")
    print("\n  Para traerlos:  python install.py --actualizar\n")
    return 0


def _actualizar() -> int:
    """Trae la versión nueva y vuelve a dejar las dependencias al día."""
    from installer import acciones, actualizacion, deteccion  # noqa: PLC0415

    try:
        actualizacion.actualizar()
    except actualizacion.HayTrabajoSinGuardar as error:
        # Lo más probable en la máquina de quien toca el código, y no es un
        # fallo: es que actualizar ahí se llevaría su trabajo por delante.
        print(f"\n  {error}\n", file=sys.stderr)
        return 1
    except actualizacion.GitError as error:
        print(f"\n  No he podido actualizar: {error}\n", file=sys.stderr)
        return 2

    raiz = deteccion.raiz_del_repo()
    python = acciones.python_del_entorno(raiz)
    if python.exists():
        # La versión nueva puede pedir dependencias que la vieja no tenía, y
        # descubrirlo al arrancar deja a Vibi muda sin decir por qué.
        print("\n  Actualizando lo que necesita…\n", flush=True)
        proceso = acciones.instalar_dependencias(raiz, python)
        for linea in proceso.stdout or ():
            print(f"    {linea.rstrip()}", flush=True)
        if proceso.wait() != 0:
            print(
                "\n  Las dependencias han fallado. Míralo aquí arriba.\n",
                file=sys.stderr,
            )
            return 2

    print("\n  Vibi está actualizada. Reiníciala para que corra la versión nueva.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

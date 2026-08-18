"""Que Windows no abra una consola cada vez que Vibi hace algo.

El agente no tiene consola propia, así que cada `subprocess` hacía parpadear
una ventana negra encima de lo que el usuario tuviera delante. Con Vibi mirando
la pantalla, leyendo ventanas y ejecutando órdenes, eso salía decenas de veces
por conversación: «quita que salte todo el rato el cmd al usar vibi»,
2026-08-17.

El test de barrido es lo que evita que vuelva: seis de los veinticuatro
procesos del nodo ya lo hacían bien, y los otros dieciocho se colaron uno a uno
sin que nadie lo notara, porque cada uno por separado parece inofensivo.
"""
import ast
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.vibi_node import proceso

RAIZ = Path(__file__).resolve().parent.parent / "agent" / "vibi_node"


class LosKwargsSegunElSistema(unittest.TestCase):
    def test_en_windows_pide_no_abrir_consola(self):
        with patch.object(sys, "platform", "win32"):
            self.assertEqual(
                proceso.sin_ventana(),
                {"creationflags": subprocess.CREATE_NO_WINDOW},
            )

    def test_fuera_de_windows_no_estorba(self):
        """`creationflags` no existe en Linux ni en macOS: pasarlo revienta."""
        with patch.object(sys, "platform", "darwin"):
            self.assertEqual(proceso.sin_ventana(), {})
            self.assertEqual(proceso.sin_ventana_en_grupo(), {})

    def test_los_de_larga_vida_ademas_salen_del_grupo(self):
        with patch.object(sys, "platform", "win32"):
            banderas = proceso.sin_ventana_en_grupo()["creationflags"]

        self.assertTrue(banderas & subprocess.CREATE_NO_WINDOW)
        self.assertTrue(banderas & subprocess.CREATE_NEW_PROCESS_GROUP)


def _llamadas_a_subprocess(arbol: ast.AST):
    """Cada `subprocess.run(...)` o `subprocess.Popen(...)` del módulo."""
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        funcion = nodo.func
        if (
            isinstance(funcion, ast.Attribute)
            and funcion.attr in {"run", "Popen"}
            and isinstance(funcion.value, ast.Name)
            and funcion.value.id == "subprocess"
        ):
            yield nodo


def _tapa_la_ventana(llamada: ast.Call) -> bool:
    """Si la llamada declara banderas, en propio o expandiendo un diccionario.

    Lo segundo se acepta porque varios módulos arman un `opciones` que ya las
    lleva dentro; el barrido no puede seguirle la pista a esa variable, así que
    aquí se fía. Lo que caza —y es lo que se cuela— es la llamada que no
    menciona el asunto en absoluto.
    """
    return any(
        clave.arg in (None, "creationflags") for clave in llamada.keywords
    )


class NingunProcesoAbreConsola(unittest.TestCase):
    def test_barrido_de_todo_el_nodo(self):
        descubiertos = []
        for archivo in sorted(RAIZ.glob("*.py")):
            arbol = ast.parse(archivo.read_text(encoding="utf-8"))
            for llamada in _llamadas_a_subprocess(arbol):
                if not _tapa_la_ventana(llamada):
                    descubiertos.append(f"{archivo.name}:{llamada.lineno}")

        self.assertEqual(
            descubiertos,
            [],
            "estos lanzan proceso sin tapar la consola; añádeles "
            "`**proceso.sin_ventana()`: " + ", ".join(descubiertos),
        )

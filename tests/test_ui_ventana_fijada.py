"""Una ventana se identifica por lo que es, no por cómo se llama ahora mismo.

El título de una ventana es lo más volátil que tiene. Spotify se retitula con
la canción que suena, Discord con el canal que miras, un navegador con la
pestaña, VS Code con el archivo. Y hasta ahora cada relectura del árbol volvía
a buscar la ventana **por su título**, así que un lote de tres pasos podía
morir a mitad porque entre el primero y el segundo empezó otra canción.

No es teórico: en el histórico de este equipo, **5 de los 10 errores de
`ui.batch` son exactamente eso** — «No hay ninguna ventana que se llame
"Spotify Free"», con Spotify delante y abierto.

El arreglo es el que usan las librerías serias de automatización de escritorio:
resolver el título **una vez**, quedarse con el identificador que da el sistema
—que no cambia mientras la ventana viva— y trabajar contra él. El título vuelve
a mirarse solo si la ventana desaparece de verdad.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import ui  # noqa: E402
from vibi_node.ui_tree import Nodo, Rect  # noqa: E402

VENTANA = Rect(0, 0, 1000, 800)
HANDLE = 777


def nodo(rol, nombre="", **kwargs):
    kwargs.setdefault("rect", Rect(10, 10, 100, 40))
    kwargs.setdefault("nativo", object())
    hijos = kwargs.pop("hijos", ())
    return Nodo(rol=rol, nombre=nombre, hijos=tuple(hijos), **kwargs)


class BackendQueSeRetitula:
    """Una ventana que cambia de nombre entre lectura y lectura, como Spotify."""

    def __init__(self, titulos: list[str]):
        # Cada lectura por título consume el siguiente; el último se repite.
        self.titulos = titulos
        self.lecturas = 0
        self.por_titulo: list[str] = []
        self.por_handle: list[int] = []

    def _titulo_actual(self) -> str:
        return self.titulos[min(self.lecturas, len(self.titulos) - 1)]

    def capturar(self, ventana=None, handle=0):
        actual = self._titulo_actual()
        if handle:
            self.por_handle.append(handle)
            if handle != HANDLE:
                raise ui.ErrorUI("sin_ventana", f"El handle {handle} ya no existe")
        else:
            self.por_titulo.append(ventana or "")
            if ventana and ventana not in actual:
                raise ui.ErrorUI(
                    "sin_ventana",
                    f"No hay ninguna ventana que se llame «{ventana}». "
                    f"Abiertas: \"{actual}\"",
                )
        self.lecturas += 1
        arbol = nodo("ventana", actual, hijos=[
            nodo("botón", "Siguiente"),
            nodo("botón", "Pausa"),
        ])
        return arbol, VENTANA, actual, (), None, HANDLE

    def handle_en_primer_plano(self):
        return HANDLE

    def sigue_vivo(self, nativo, huella):
        return True

    def disponible(self):
        return True

    def clic(self, elemento, boton="left", veces=1, entrada_global=True):
        return "patrón invocar"

    def escribir(self, elemento, texto, entrada_global=True):
        return "patrón valor"

    def seleccionar(self, elemento):
        return "patrón seleccionar"

    def expandir(self, elemento):
        return "patrón expandir"

    def contraer(self, elemento):
        return "patrón contraer"

    def enfocar(self, elemento):
        pass

    def activar(self, handle):
        return True

    def valor_de(self, elemento):
        return None

    def nombre_de(self, elemento):
        return ""


class BaseFijada(TestCase):
    def setUp(self):
        ui.olvidar()
        self.addCleanup(ui.olvidar)
        parche = patch.object(ui, "ESPERA_ASENTAR", 0)
        parche.start()
        self.addCleanup(parche.stop)
        patch("vibi_node.computer.pulsar").start()
        patch("vibi_node.computer.teclear").start()
        self.addCleanup(patch.stopall)

    def montar(self, *titulos):
        backend = BackendQueSeRetitula(list(titulos))
        parche = patch.object(ui, "_backend", return_value=backend)
        parche.start()
        self.addCleanup(parche.stop)
        return backend


class ElTituloCambiaAMitadDelLote(BaseFijada):
    def test_el_lote_sobrevive_al_cambio_de_título(self):
        backend = self.montar(
            "Spotify Free",
            "MegaR - JACKALS",       # empezó otra canción
            "MegaR - JACKALS",
        )

        salida = ui.ejecutar_lote(
            [
                {"accion": "clic", "buscar": {"nombre": "Siguiente"}},
                {"accion": "clic", "buscar": {"nombre": "Pausa"}},
            ],
            ventana="Spotify Free",
        )

        self.assertIsNone(salida["error"], salida["pasos"])
        self.assertEqual(salida["completados"], 2)

    def test_el_título_se_resuelve_una_sola_vez(self):
        backend = self.montar("Spotify Free", "MegaR - JACKALS")

        ui.ejecutar_lote(
            [
                {"accion": "clic", "buscar": {"nombre": "Siguiente"}},
                {"accion": "clic", "buscar": {"nombre": "Pausa"}},
            ],
            ventana="Spotify Free",
        )

        # Una búsqueda por título, y el resto contra el identificador.
        self.assertEqual(backend.por_titulo, ["Spotify Free"])
        self.assertTrue(backend.por_handle)
        self.assertTrue(all(h == HANDLE for h in backend.por_handle))

    def test_sin_ventana_pedida_también_se_fija(self):
        """Sin título es «la que está delante», y sigue siendo esa todo el lote."""
        backend = self.montar("Lo que sea", "Otra cosa")

        salida = ui.ejecutar_lote(
            [
                {"accion": "clic", "buscar": {"nombre": "Siguiente"}},
                {"accion": "clic", "buscar": {"nombre": "Pausa"}},
            ]
        )

        self.assertIsNone(salida["error"], salida["pasos"])
        self.assertTrue(backend.por_handle)


class SiLaVentanaNoEstaAlEmpezar(BaseFijada):
    """Sin ventana no hay nada que fijar: se para antes de empezar, como siempre."""

    def test_se_dice_con_la_lista_de_las_que_hay(self):
        self.montar("Otra cosa distinta")

        with self.assertRaises(ui.ErrorUI) as caso:
            ui.ejecutar_lote(
                [{"accion": "clic", "buscar": {"nombre": "Siguiente"}}],
                ventana="Spotify Free",
            )

        self.assertIn("Otra cosa distinta", caso.exception.mensaje)


class SiLaVentanaSeCierraAMitad(BaseFijada):
    """Fijarla no la resucita: si desaparece, el lote lo dice y para."""

    def test_el_lote_para_y_lo_explica(self):
        backend = self.montar("App")

        def morir(ventana=None, handle=0):
            if handle:
                raise ui.ErrorUI(
                    "sin_ventana",
                    "La ventana con la que estabas trabajando ya no existe.",
                )
            return BackendQueSeRetitula.capturar(backend, ventana)

        backend.capturar = morir

        salida = ui.ejecutar_lote(
            [
                {"accion": "clic", "buscar": {"nombre": "Siguiente"}},
                {"accion": "clic", "buscar": {"nombre": "Pausa"}},
            ],
            ventana="App",
        )

        self.assertEqual(salida["error"], "sin_ventana")
        self.assertEqual(salida["completados"], 1)


class BackendSinHandle(BaseFijada):
    """Uno que no acepta handle sigue funcionando por título, como antes."""

    def test_no_revienta(self):
        class Viejo(BackendQueSeRetitula):
            def capturar(self, ventana=None):
                self.por_titulo.append(ventana or "")
                actual = self._titulo_actual()
                self.lecturas += 1
                arbol = nodo("ventana", actual, hijos=[nodo("botón", "Siguiente")])
                return arbol, VENTANA, actual, (), None

        backend = Viejo(["App"])
        parche = patch.object(ui, "_backend", return_value=backend)
        parche.start()
        self.addCleanup(parche.stop)

        salida = ui.ejecutar_lote(
            [{"accion": "clic", "buscar": {"nombre": "Siguiente"}}]
        )

        self.assertIsNone(salida["error"], salida["pasos"])

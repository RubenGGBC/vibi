"""El teclado y el ratón no van a la ventana que miras, van a la que está delante.

Esta es la distinción que costó un WhatsApp el 19/08/2026. El árbol se leyó de
una ventana en segundo plano —el propio snapshot avisaba de ello— y después se
actuó con teclado y ratón globales, que fueron a parar al navegador que sí
estaba delante. El mensaje se tecleó sobre un vídeo de YouTube, cuyos espacios
son la barra espaciadora, y Vibi dio la tarea por hecha.

Lo que se prueba aquí es la regla que lo impide: **si la ventana no está en
primer plano, la entrada global está prohibida**. No desaconsejada por el
prompt: rechazada por el nodo, con un error que dice qué hacer.

Los patrones de UIA sí siguen permitidos, y ese es justo el matiz: pulsar un
botón por `Invoke` es la aplicación ejecutando su propia acción y no depende de
dónde esté la ventana. Prohibirlo también sería tirar lo único que funciona
bien en segundo plano.
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

# El handle de la ventana que se está mirando, y el de la que tiene el foco.
# Que sean distintos es todo el escenario del fallo.
MIRADA = 1001
OTRA = 2002


def nodo(rol, nombre="", **kwargs):
    kwargs.setdefault("rect", Rect(10, 10, 100, 40))
    kwargs.setdefault("nativo", object())
    hijos = kwargs.pop("hijos", ())
    return Nodo(rol=rol, nombre=nombre, hijos=tuple(hijos), **kwargs)


class BackendConFoco:
    """Un escritorio de mentira que sabe qué ventana está delante."""

    def __init__(self, arbol, handle_mirado=MIRADA, handle_delante=MIRADA):
        self.arbol = arbol
        self.handle_mirado = handle_mirado
        self.handle_delante = handle_delante
        self.hechas: list[tuple] = []
        # Lo que la ventana admite por patrón. Vacío = todo cae a la entrada
        # global, que es el caso peligroso.
        self.patrones = {"clic", "escribir", "seleccionar", "enfocar"}
        # Windows puede negarle el primer plano a un proceso de fondo.
        self.deja_activar = True

    # --- lectura ---
    def capturar(self, ventana=None):
        return self.arbol, VENTANA, "App", ("Otra",), None, self.handle_mirado

    def handle_en_primer_plano(self):
        return self.handle_delante

    def activar(self, handle):
        self.hechas.append(("activar", handle))
        if not self.deja_activar:
            return False
        self.handle_delante = handle
        return True

    def sigue_vivo(self, nativo, huella):
        return True

    def disponible(self):
        return True

    # --- acciones ---
    def clic(self, elemento, boton="left", veces=1, entrada_global=True):
        if "clic" in self.patrones:
            self.hechas.append(("clic", "patrón"))
            return "patrón invocar"
        if not entrada_global:
            raise ui.ErrorUI(
                "ventana_de_fondo",
                "No admite pulsarse por patrón y la ventana no está delante.",
            )
        self.hechas.append(("clic", "ratón"))
        return "ratón"

    def escribir(self, elemento, texto, entrada_global=True):
        if "escribir" in self.patrones:
            self.hechas.append(("escribir", texto, "patrón"))
            return "patrón valor"
        if not entrada_global:
            raise ui.ErrorUI(
                "ventana_de_fondo",
                "Ese campo hay que teclearlo y la ventana no está delante.",
            )
        self.hechas.append(("escribir", texto, "teclado"))
        return "teclado"

    def seleccionar(self, elemento):
        self.hechas.append(("seleccionar",))
        return "patrón seleccionar"

    def expandir(self, elemento):
        self.hechas.append(("expandir",))
        return "patrón expandir"

    def contraer(self, elemento):
        self.hechas.append(("contraer",))
        return "patrón contraer"

    def enfocar(self, elemento):
        self.hechas.append(("enfocar",))


def arbol(*hijos):
    return nodo("ventana", "App", hijos=hijos)


class BaseFoco(TestCase):
    def setUp(self):
        ui.olvidar()
        self.addCleanup(ui.olvidar)
        parche = patch.object(ui, "ESPERA_ASENTAR", 0)
        parche.start()
        self.addCleanup(parche.stop)
        # El teclado de verdad no se toca en ninguna prueba: si algo llega
        # hasta aquí, es que la guardia no ha hecho su trabajo.
        self.teclado = patch("vibi_node.computer.pulsar").start()
        self.escritura = patch("vibi_node.computer.teclear").start()
        self.addCleanup(patch.stopall)

    def montar(self, arbol_inicial, delante=MIRADA, patrones=None):
        backend = BackendConFoco(arbol_inicial, handle_delante=delante)
        if patrones is not None:
            backend.patrones = set(patrones)
        parche = patch.object(ui, "_backend", return_value=backend)
        parche.start()
        self.addCleanup(parche.stop)
        return backend


class TeclasSueltas(BaseFoco):
    """`tecla` no tiene objetivo: siempre va a la ventana que esté delante."""

    def test_con_la_ventana_delante_la_tecla_se_pulsa(self):
        self.montar(arbol(nodo("campo", "Mensaje")), delante=MIRADA)

        salida = ui.ejecutar_lote([{"accion": "tecla", "tecla": "enter"}])

        self.assertEqual(salida["pasos"][0]["estado"], "ok")
        self.teclado.assert_called_once()

    def test_con_la_ventana_detras_la_tecla_se_rechaza(self):
        self.montar(arbol(nodo("campo", "Mensaje")), delante=OTRA)

        salida = ui.ejecutar_lote(
            [{"accion": "tecla", "tecla": "enter"}], ventana="App"
        )

        paso = salida["pasos"][0]
        self.assertEqual(paso["estado"], "error")
        self.assertEqual(paso["error"], "ventana_de_fondo")
        # Y sobre todo: no se ha pulsado nada en la ventana de otro.
        self.teclado.assert_not_called()

    def test_el_error_dice_qué_ventana_se_habría_llevado_la_tecla(self):
        self.montar(arbol(nodo("campo", "Mensaje")), delante=OTRA)

        salida = ui.ejecutar_lote(
            [{"accion": "tecla", "tecla": "enter"}], ventana="App"
        )

        detalle = salida["pasos"][0]["detalle"]
        self.assertIn("App", detalle)
        self.assertIn("delante", detalle.lower())


class EscribirAlAire(BaseFoco):
    """`escribir` sin objetivo teclea donde esté el foco: mismo peligro."""

    def test_sin_objetivo_y_con_la_ventana_detras_se_rechaza(self):
        self.montar(arbol(nodo("campo", "Mensaje")), delante=OTRA)

        salida = ui.ejecutar_lote(
            [{"accion": "escribir", "texto": "hola"}], ventana="App"
        )

        self.assertEqual(salida["pasos"][0]["error"], "ventana_de_fondo")
        self.escritura.assert_not_called()

    def test_sin_objetivo_y_con_la_ventana_delante_se_teclea(self):
        self.montar(arbol(nodo("campo", "Mensaje")), delante=MIRADA)

        salida = ui.ejecutar_lote([{"accion": "escribir", "texto": "hola"}])

        self.assertEqual(salida["pasos"][0]["estado"], "ok")
        self.escritura.assert_called_once_with("hola")


class LoQueSiguePermitido(BaseFoco):
    """Los patrones de UIA no dependen del foco, y no se tocan."""

    def test_pulsar_por_patrón_funciona_con_la_ventana_detrás(self):
        backend = self.montar(
            arbol(nodo("botón", "Enviar")), delante=OTRA
        )

        salida = ui.ejecutar_lote(
            [{"accion": "clic", "buscar": {"nombre": "Enviar"}}],
            ventana="App",
        )

        self.assertEqual(salida["pasos"][0]["estado"], "ok")
        self.assertEqual(backend.hechas, [("clic", "patrón")])

    def test_escribir_en_un_campo_por_patrón_funciona_con_la_ventana_detrás(self):
        backend = self.montar(arbol(nodo("campo", "Mensaje")), delante=OTRA)

        salida = ui.ejecutar_lote(
            [{
                "accion": "escribir",
                "buscar": {"nombre": "Mensaje"},
                "texto": "hola",
            }],
            ventana="App",
        )

        self.assertEqual(salida["pasos"][0]["estado"], "ok")
        self.assertEqual(backend.hechas, [("escribir", "hola", "patrón")])


class CuandoElPatronNoExiste(BaseFoco):
    """Lo que hoy cae al ratón sin avisar: ahí es donde se pinchaba a ciegas."""

    def test_un_clic_sin_patrón_no_cae_al_ratón_si_la_ventana_está_detrás(self):
        backend = self.montar(
            arbol(nodo("celda", "Andorra")), delante=OTRA, patrones=set()
        )

        salida = ui.ejecutar_lote(
            [{"accion": "clic", "buscar": {"nombre": "Andorra"}}],
            ventana="App",
        )

        self.assertEqual(salida["pasos"][0]["error"], "ventana_de_fondo")
        self.assertEqual(backend.hechas, [])

    def test_un_clic_sin_patrón_sí_usa_el_ratón_si_la_ventana_está_delante(self):
        backend = self.montar(
            arbol(nodo("celda", "Andorra")), delante=MIRADA, patrones=set()
        )

        salida = ui.ejecutar_lote(
            [{"accion": "clic", "buscar": {"nombre": "Andorra"}}]
        )

        self.assertEqual(salida["pasos"][0]["estado"], "ok")
        self.assertEqual(backend.hechas, [("clic", "ratón")])


class TraerLaVentanaAlFrente(BaseFoco):
    """La salida del bloqueo: robar el foco a propósito, no sin querer.

    Prohibir el teclado a ciegas sin dar una forma de arreglarlo sería dejar
    tareas sin salida. `activar` es esa forma, y la diferencia con lo de antes
    es que ahora es una decisión declarada: aparece en los pasos, se puede
    contar, y quien la pide sabe que va a tapar lo que hubiera delante.
    """

    def test_activar_pone_la_ventana_delante_y_entonces_sí_se_teclea(self):
        backend = self.montar(arbol(nodo("campo", "Mensaje")), delante=OTRA)

        salida = ui.ejecutar_lote(
            [
                {"accion": "activar"},
                {"accion": "tecla", "tecla": "enter"},
            ],
            ventana="App",
        )

        self.assertIsNone(salida["error"], salida["pasos"])
        self.assertEqual(backend.handle_delante, MIRADA)
        self.teclado.assert_called_once()

    def test_si_windows_niega_el_frente_se_dice_y_no_se_teclea(self):
        backend = self.montar(arbol(nodo("campo", "Mensaje")), delante=OTRA)
        backend.deja_activar = False

        salida = ui.ejecutar_lote(
            [
                {"accion": "activar"},
                {"accion": "tecla", "tecla": "enter"},
            ],
            ventana="App",
        )

        self.assertEqual(salida["pasos"][0]["error"], "sin_primer_plano")
        # El lote para al primer fallo, así que la tecla ni se intenta.
        self.assertEqual(len(salida["pasos"]), 1)
        self.teclado.assert_not_called()

    def test_un_backend_que_sabe_el_foco_pero_no_activar_lo_dice(self):
        class SinActivar(BackendConFoco):
            def __getattribute__(self, nombre):
                if nombre == "activar":
                    raise AttributeError(nombre)
                return super().__getattribute__(nombre)

        backend = SinActivar(arbol(nodo("campo", "Mensaje")), handle_delante=OTRA)
        parche = patch.object(ui, "_backend", return_value=backend)
        parche.start()
        self.addCleanup(parche.stop)

        salida = ui.ejecutar_lote([{"accion": "activar"}], ventana="App")

        self.assertEqual(salida["pasos"][0]["error"], "sin_activar")

    def test_activar_con_la_ventana_ya_delante_no_hace_nada(self):
        backend = self.montar(arbol(nodo("campo", "Mensaje")), delante=MIRADA)

        salida = ui.ejecutar_lote([{"accion": "activar"}], ventana="App")

        self.assertEqual(salida["pasos"][0]["estado"], "ok")
        self.assertEqual(backend.hechas, [])


class BackendMudo(BackendConFoco):
    """Un backend que no publica el foco: el de macOS a día de hoy."""

    def __getattribute__(self, nombre):
        if nombre in ("handle_en_primer_plano", "activar"):
            raise AttributeError(nombre)
        return super().__getattribute__(nombre)

    def capturar(self, ventana=None):
        # Ni siquiera devuelve handle: es la tupla de cinco de toda la vida.
        return self.arbol, VENTANA, "App", ("Otra",), None


class SinSaberElFoco(BaseFoco):
    """Un backend que no sabe decir qué hay delante no puede bloquear nada.

    Es el caso de macOS, escrito a ciegas. Prohibir por una comprobación que no
    se puede hacer sería romper lo que hoy funciona allí. Y de paso prueba que
    un backend con la firma vieja —cinco elementos, sin handle— sigue valiendo.
    """

    def test_si_el_backend_no_sabe_el_foco_no_se_bloquea(self):
        backend = BackendMudo(arbol(nodo("campo", "Mensaje")))
        parche = patch.object(ui, "_backend", return_value=backend)
        parche.start()
        self.addCleanup(parche.stop)

        salida = ui.ejecutar_lote(
            [{"accion": "tecla", "tecla": "enter"}], ventana="App"
        )

        self.assertEqual(salida["pasos"][0]["estado"], "ok")
        self.teclado.assert_called_once()

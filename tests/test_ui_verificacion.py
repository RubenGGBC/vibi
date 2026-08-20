"""Escribir no es haber escrito, y hay que mirarlo en el árbol de después.

Medido en esta máquina el 20/08/2026, con Discord y WhatsApp abiertos:

* **Discord** acepta `ValuePattern.SetValue` en su cuadro de mensaje con la
  ventana detrás, y el texto entra de verdad: 6 ms, confirmado releyendo.
* **WhatsApp** acepta la llamada, **y encima devuelve el texto si le preguntas
  al mismo objeto** — pero el cuadro real se queda con un salto de línea. El
  mensaje nunca se escribió.

Ese segundo caso es el que hace que comprobar no sea opcional, y también el que
dice **cómo** hay que comprobar: preguntarle al elemento que acabas de tocar no
vale, porque contesta lo que le pusiste. Hay que volver a leer la ventana y
mirar cómo quedó, que es lo que haría una persona.

Es el fallo exacto del 19/08/2026: seis órdenes en verde, ningún mensaje
enviado, y Vibi diciendo que estaba hecho.
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
HANDLE = 4242


def nodo(rol, nombre="", **kwargs):
    kwargs.setdefault("rect", Rect(10, 10, 100, 40))
    kwargs.setdefault("nativo", object())
    hijos = kwargs.pop("hijos", ())
    return Nodo(rol=rol, nombre=nombre, hijos=tuple(hijos), **kwargs)


class Campo:
    """Un cuadro de texto de mentira, con la avería de WhatsApp opcional."""

    def __init__(self, nombre: str, miente: bool = False):
        self.nombre = nombre
        self.miente = miente
        # Lo que el campo enseña de verdad al releerlo.
        self.real = ""
        # Lo que contesta el objeto al que le escribiste. En WhatsApp esto y
        # lo anterior no coinciden, y ahí está toda la trampa.
        self.recordado = ""

    def poner(self, texto: str) -> None:
        self.recordado = texto
        if not self.miente:
            self.real = texto


class BackendConCampos:
    def __init__(self, campos: list[Campo], delante: int = HANDLE):
        self.campos = campos
        self.delante = delante
        self.escrituras: list[tuple[str, str]] = []

    def _arbol(self):
        return nodo(
            "ventana",
            "App",
            hijos=[nodo("campo", c.nombre, nativo=c) for c in self.campos],
        )

    def capturar(self, ventana=None):
        return self._arbol(), VENTANA, "App", (), None, HANDLE

    def handle_en_primer_plano(self):
        return self.delante

    def sigue_vivo(self, nativo, huella):
        return True

    def disponible(self):
        return True

    # --- lo que hace falta para verificar ---
    def valor_de(self, elemento):
        return elemento.real if isinstance(elemento, Campo) else None

    def nombre_de(self, elemento):
        return elemento.nombre if isinstance(elemento, Campo) else ""

    # --- acciones ---
    def escribir(self, elemento, texto, entrada_global=True):
        elemento.poner(texto)
        self.escrituras.append((elemento.nombre, texto))
        return "patrón valor"

    def clic(self, elemento, boton="left", veces=1, entrada_global=True):
        return "patrón invocar"

    def seleccionar(self, elemento):
        return "patrón seleccionar"

    def expandir(self, elemento):
        return "patrón expandir"

    def contraer(self, elemento):
        return "patrón contraer"

    def enfocar(self, elemento):
        pass

    def activar(self, handle):
        self.delante = handle
        return True


class BaseVerificacion(TestCase):
    def setUp(self):
        ui.olvidar()
        self.addCleanup(ui.olvidar)
        parche = patch.object(ui, "ESPERA_ASENTAR", 0)
        parche.start()
        self.addCleanup(parche.stop)
        patch("vibi_node.computer.pulsar").start()
        patch("vibi_node.computer.teclear").start()
        self.addCleanup(patch.stopall)

    def montar(self, *campos):
        backend = BackendConCampos(list(campos))
        parche = patch.object(ui, "_backend", return_value=backend)
        parche.start()
        self.addCleanup(parche.stop)
        return backend


class CuandoElTextoEntra(BaseVerificacion):
    def test_se_da_por_bueno_y_se_dice_que_está_comprobado(self):
        self.montar(Campo("Enviar mensaje a #general"))

        salida = ui.ejecutar_lote([{
            "accion": "escribir",
            "buscar": {"nombre": "Enviar mensaje"},
            "texto": "voy en 10",
        }])

        paso = salida["pasos"][0]
        self.assertEqual(paso["estado"], "ok")
        self.assertIn("comprobado", paso["via"])
        self.assertIsNone(salida["error"])


class CuandoElTextoNoEntra(BaseVerificacion):
    """La avería de WhatsApp: acepta, recuerda, y el cuadro sigue vacío."""

    def test_el_paso_se_marca_como_error_aunque_la_llamada_no_fallara(self):
        backend = self.montar(Campo("Escribir un mensaje", miente=True))

        salida = ui.ejecutar_lote([{
            "accion": "escribir",
            "buscar": {"nombre": "Escribir un mensaje"},
            "texto": "y sigue siendo un palo",
        }])

        paso = salida["pasos"][0]
        # La llamada al backend sí se hizo y sí dijo que todo bien...
        self.assertEqual(len(backend.escrituras), 1)
        # ...y aun así el paso es un fallo, porque el texto no está.
        self.assertEqual(paso["estado"], "error")
        self.assertEqual(paso["error"], "no_entro")
        self.assertEqual(salida["error"], "no_entro")

    def test_el_lote_para_ahí_y_no_manda_el_enter(self):
        self.montar(Campo("Escribir un mensaje", miente=True))

        salida = ui.ejecutar_lote([
            {
                "accion": "escribir",
                "buscar": {"nombre": "Escribir un mensaje"},
                "texto": "hola",
            },
            {"accion": "tecla", "tecla": "enter"},
        ])

        # Enviar un mensaje vacío es peor que no enviarlo: el lote para antes.
        self.assertEqual(len(salida["pasos"]), 1)
        self.assertEqual(salida["completados"], 0)

    def test_el_error_explica_qué_pasó_sin_culpar_al_modelo(self):
        self.montar(Campo("Escribir un mensaje", miente=True))

        salida = ui.ejecutar_lote([{
            "accion": "escribir",
            "buscar": {"nombre": "Escribir un mensaje"},
            "texto": "hola",
        }])

        detalle = salida["pasos"][0]["detalle"].lower()
        self.assertIn("no", detalle)
        # Tiene que decir la salida, o el modelo se queda sin saber qué hacer.
        self.assertTrue(
            "activar" in detalle or "delante" in detalle,
            detalle,
        )


class LoQueNoSePuedeComprobar(BaseVerificacion):
    """Un campo que no publica su valor no es un fallo, pero tampoco un sí."""

    def test_se_dice_que_no_se_ha_podido_comprobar(self):
        class Mudo(Campo):
            pass

        backend = self.montar(Mudo("Campo raro"))
        backend.valor_de = lambda elemento: None

        salida = ui.ejecutar_lote([{
            "accion": "escribir",
            "buscar": {"nombre": "Campo raro"},
            "texto": "hola",
        }])

        paso = salida["pasos"][0]
        self.assertEqual(paso["estado"], "ok")
        self.assertIn("sin comprobar", paso["via"])


class BackendViejo(BaseVerificacion):
    """Uno que no sabe leer valores sigue funcionando, sin verificar."""

    def test_no_revienta_ni_bloquea(self):
        class SinValorDe(BackendConCampos):
            def __getattribute__(self, nombre):
                if nombre in ("valor_de", "nombre_de"):
                    raise AttributeError(nombre)
                return super().__getattribute__(nombre)

        backend = SinValorDe([Campo("Campo")])
        parche = patch.object(ui, "_backend", return_value=backend)
        parche.start()
        self.addCleanup(parche.stop)

        salida = ui.ejecutar_lote([{
            "accion": "escribir",
            "buscar": {"nombre": "Campo"},
            "texto": "hola",
        }])

        self.assertEqual(salida["pasos"][0]["estado"], "ok")

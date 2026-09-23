"""Señalar: qué se marca, dónde cae la marca y cuándo hay que decir que no.

Con monitores y ventanas de mentira, porque lo que se prueba aquí es la
aritmética y la disciplina —dónde cae un rectángulo dentro de la foto, qué pasa
con un `ref` que ya no es el que era— y no si UIA publica bien los límites de un
botón. Eso último solo lo puede decir una máquina con ventanas de verdad.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import guia, ui, ui_tree  # noqa: E402
from vibi_node.ui_tree import Nodo, Rect  # noqa: E402

VENTANA = Rect(0, 0, 1000, 800)

# Una ventana estirada entre los dos monitores. Hace falta porque `ui_tree`
# poda lo que cae fuera del rectángulo de la ventana: sin esto, un botón en el
# monitor de la izquierda no llegaría siquiera al árbol.
VENTANA_ANCHA = Rect(-1920, 0, 1920, 1080)

# La misma disposición que en `test_screen`: el secundario a la izquierda, en
# coordenadas negativas, que es lo que rompe las cuentas ingenuas.
DOS_PANTALLAS = [
    {
        "numero": 1, "x": 0, "y": 0, "ancho": 1920, "alto": 1080,
        "principal": True, "con_cursor": True,
    },
    {
        "numero": 2, "x": -1920, "y": 0, "ancho": 1920, "alto": 1080,
        "principal": False, "con_cursor": False,
    },
]

# Lo que devuelve una captura de la principal reducida a 1568 px de lado largo.
FOTO_PRINCIPAL = {
    "pantalla": "pantalla 1 (principal)",
    "ancho": 1568, "alto": 882,
    "ancho_real": 1920, "alto_real": 1080,
    "origen_x": 0, "origen_y": 0,
}

# Y una de la que vive en negativo.
FOTO_SECUNDARIA = {
    **FOTO_PRINCIPAL,
    "pantalla": "pantalla 2",
    "origen_x": -1920,
}


def nodo(rol, nombre="", **kwargs):
    kwargs.setdefault("rect", Rect(100, 100, 300, 140))
    kwargs.setdefault("nativo", object())
    kwargs.setdefault("accionable", True)
    hijos = kwargs.pop("hijos", ())
    return Nodo(rol=rol, nombre=nombre, hijos=tuple(hijos), **kwargs)


class BackendFalso:
    """Un escritorio de mentira que apunta si alguien intenta tocarlo."""

    def __init__(self, arboles, rect=VENTANA):
        self.arboles = list(arboles)
        self.rect = rect
        self.lecturas = 0
        self.hechas: list[str] = []

    def capturar(self, ventana=None, handle=0):
        indice = min(self.lecturas, len(self.arboles) - 1)
        self.lecturas += 1
        return self.arboles[indice], self.rect, "App", ("Otra",), None, 7

    def sigue_vivo(self, nativo, huella):
        return True

    def __getattr__(self, nombre):
        # Cualquier acción —clic, escribir, activar— queda apuntada. Una guía
        # que llamara a alguna dejaría de ser una guía.
        def accion(*args, **kwargs):
            self.hechas.append(nombre)
        return accion


class Proyectar(TestCase):
    """De un rectángulo del escritorio al mismo dentro de la foto."""

    def test_escala_al_tamano_de_la_imagen(self):
        # 1920 → 1568 es 0,81666…: un botón que empieza en x=960 cae en 784.
        caja = guia.proyectar(Rect(960, 540, 1160, 580), FOTO_PRINCIPAL)
        self.assertEqual(caja["x"], round(960 * 1568 / 1920) - guia.HOLGURA)
        self.assertEqual(caja["y"], round(540 * 882 / 1080) - guia.HOLGURA)
        self.assertEqual(
            caja["ancho"], round(200 * 1568 / 1920) + 2 * guia.HOLGURA
        )
        self.assertFalse(caja["recortada"])

    def test_el_monitor_en_negativo_se_resta_antes_de_escalar(self):
        # Un botón a 60 px del borde izquierdo del monitor secundario vive en
        # x=-1860 dentro del escritorio, y en la foto tiene que caer cerca del
        # borde izquierdo, no fuera.
        caja = guia.proyectar(Rect(-1860, 100, -1760, 140), FOTO_SECUNDARIA)
        self.assertEqual(caja["x"], round(60 * 1568 / 1920) - guia.HOLGURA)
        self.assertGreater(caja["ancho"], 0)

    def test_lo_que_sale_a_medias_se_marca_con_lo_que_se_ve(self):
        caja = guia.proyectar(Rect(-40, 100, 200, 140), FOTO_PRINCIPAL)
        self.assertEqual(caja["x"], 0)
        self.assertTrue(caja["recortada"])
        self.assertGreater(caja["ancho"], 0)

    def test_lo_que_esta_en_el_otro_monitor_no_se_marca(self):
        self.assertIsNone(
            guia.proyectar(Rect(-1800, 100, -1700, 140), FOTO_PRINCIPAL)
        )

    def test_sin_mapa_no_se_inventa_una_marca(self):
        self.assertIsNone(guia.proyectar(Rect(0, 0, 10, 10), {}))


class ElegirPantalla(TestCase):
    def test_coge_el_monitor_donde_esta_el_elemento(self):
        self.assertEqual(
            guia._pantalla_de(Rect(-1800, 100, -1700, 140), DOS_PANTALLAS), "2"
        )
        self.assertEqual(
            guia._pantalla_de(Rect(100, 100, 200, 140), DOS_PANTALLAS), "1"
        )

    def test_lo_que_no_cae_en_ninguno_deja_elegir_a_la_captura(self):
        # Vacío es «la que tenga el ratón», que es lo que significa «mi
        # pantalla» cuando nadie ha dicho cuál.
        self.assertEqual(
            guia._pantalla_de(Rect(9000, 9000, 9100, 9040), DOS_PANTALLAS), ""
        )


class LoQuePideElModelo(TestCase):
    def test_sin_objetivos_no_hay_guia(self):
        with self.assertRaises(ui.ErrorUI) as caso:
            guia._descriptores([])
        self.assertEqual(caso.exception.codigo, "sin_objetivos")

    def test_mas_de_seis_marcas_se_rechaza_y_se_dice_qué_hacer(self):
        with self.assertRaises(ui.ErrorUI) as caso:
            guia._descriptores([{"ref": f"e{n}"} for n in range(7)])
        self.assertEqual(caso.exception.codigo, "demasiadas_marcas")
        self.assertIn("varias guías", caso.exception.mensaje)

    def test_un_objetivo_sin_nada_con_lo_que_buscarlo(self):
        with self.assertRaises(ui.ErrorUI) as caso:
            guia._descriptores([{"texto": "aquí"}])
        self.assertEqual(caso.exception.codigo, "descriptor_vacio")

    def test_la_etiqueta_de_la_leyenda_se_recorta(self):
        [descriptor] = guia._descriptores([{"ref": "e1", "texto": "x" * 500}])
        self.assertEqual(len(descriptor["texto"]), guia.MAX_TEXTO)


class Senalar(TestCase):
    def setUp(self):
        ui.olvidar()
        self.addCleanup(ui.olvidar)

    def _montar(self, backend, foto=None):
        detalle = dict(foto or FOTO_PRINCIPAL)
        parches = [
            patch.object(ui, "_backend", lambda: backend),
            patch.object(guia.screen, "pantallas", lambda: DOS_PANTALLAS),
            patch.object(
                guia.screen,
                "capturar",
                lambda pantalla="": {
                    "jpeg": b"jpeg-de-mentira",
                    "detalle": {**detalle, "pedida": pantalla},
                },
            ),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)

    def test_marca_numerada_sobre_el_elemento_y_sin_tocar_nada(self):
        arbol = nodo("ventana", "App", hijos=[
            nodo("boton", "Guardar", rect=Rect(200, 300, 320, 340)),
        ])
        backend = BackendFalso([arbol])
        self._montar(backend)

        salida = guia.senalar([{"rol": "boton", "nombre": "Guardar",
                                "texto": "este"}])

        self.assertEqual(salida["jpeg"], b"jpeg-de-mentira")
        [marca] = salida["marcas"]
        self.assertEqual(marca["numero"], 1)
        self.assertEqual(marca["nombre"], "Guardar")
        self.assertEqual(marca["texto"], "este")
        self.assertEqual(marca["x"], round(200 * 1568 / 1920) - guia.HOLGURA)
        # Lo importante: nadie ha pulsado nada.
        self.assertEqual(backend.hechas, [])

    def test_pide_la_foto_del_monitor_donde_esta_lo_que_señala(self):
        arbol = nodo("ventana", "App", rect=VENTANA_ANCHA, hijos=[
            nodo("boton", "Guardar", rect=Rect(-1800, 300, -1700, 340)),
        ])
        self._montar(BackendFalso([arbol], VENTANA_ANCHA), FOTO_SECUNDARIA)

        salida = guia.senalar([{"rol": "boton", "nombre": "Guardar"}])

        self.assertEqual(salida["detalle"]["pantalla"], "pantalla 2")
        self.assertTrue(salida["marcas"])

    def test_lo_que_no_cabe_en_la_foto_se_dice_en_vez_de_callarlo(self):
        arbol = nodo("ventana", "App", rect=VENTANA_ANCHA, hijos=[
            nodo("boton", "Guardar", rect=Rect(200, 300, 320, 340)),
            nodo("boton", "Otra pantalla", rect=Rect(-1800, 300, -1700, 340)),
        ])
        self._montar(BackendFalso([arbol], VENTANA_ANCHA))

        salida = guia.senalar([
            {"rol": "boton", "nombre": "Guardar"},
            {"rol": "boton", "nombre": "Otra pantalla"},
        ])

        self.assertEqual(len(salida["marcas"]), 1)
        self.assertEqual(salida["detalle"]["fuera"], ["Otra pantalla"])

    def test_si_no_se_ve_nada_de_lo_pedido_es_un_error(self):
        arbol = nodo("ventana", "App", rect=VENTANA_ANCHA, hijos=[
            nodo("boton", "Guardar", rect=Rect(-1800, 300, -1700, 340)),
        ])
        self._montar(BackendFalso([arbol], VENTANA_ANCHA))

        with self.assertRaises(ui.ErrorUI) as caso:
            guia.senalar([{"rol": "boton", "nombre": "Guardar"}])
        self.assertEqual(caso.exception.codigo, "fuera_de_pantalla")

    def test_varios_candidatos_se_enumeran_en_vez_de_señalar_el_primero(self):
        arbol = nodo("ventana", "App", hijos=[
            nodo("boton", "Aceptar", rect=Rect(100, 100, 200, 140)),
            nodo("boton", "Aceptar", rect=Rect(300, 100, 400, 140)),
        ])
        self._montar(BackendFalso([arbol]))

        with self.assertRaises(ui.ErrorUI) as caso:
            guia.senalar([{"rol": "boton", "nombre": "Aceptar"}])
        self.assertEqual(caso.exception.codigo, "ambiguo")
        self.assertEqual(len(caso.exception.datos["candidatos"]), 2)

    def test_lo_que_no_esta_manda_a_volver_a_mirar(self):
        arbol = nodo("ventana", "App", hijos=[nodo("boton", "Guardar")])
        self._montar(BackendFalso([arbol]))

        with self.assertRaises(ui.ErrorUI) as caso:
            guia.senalar([{"rol": "boton", "nombre": "Imprimir"}])
        self.assertEqual(caso.exception.codigo, "no_encontrado")

    def test_un_ref_de_la_ultima_lectura_señala_lo_mismo(self):
        arbol = nodo("ventana", "App", hijos=[
            nodo("boton", "Guardar", rect=Rect(200, 300, 320, 340)),
        ])
        backend = BackendFalso([arbol])
        self._montar(backend)
        ui.capturar()  # la lectura previa, la que le dio los ref al modelo

        salida = guia.senalar([{"ref": "e1"}])

        self.assertEqual(salida["marcas"][0]["nombre"], "Guardar")

    def test_un_ref_que_ha_pasado_a_ser_otra_cosa_no_se_señala(self):
        antes = nodo("ventana", "App", hijos=[
            nodo("boton", "Guardar", rect=Rect(200, 300, 320, 340)),
        ])
        despues = nodo("ventana", "App", hijos=[
            nodo("boton", "Borrar", rect=Rect(200, 300, 320, 340)),
        ])
        backend = BackendFalso([antes, despues])
        self._montar(backend)
        ui.capturar()

        with self.assertRaises(ui.ErrorUI) as caso:
            guia.senalar([{"ref": "e1"}])
        self.assertEqual(caso.exception.codigo, "ref_caducado")
        self.assertIn("Borrar", caso.exception.mensaje)

    def test_un_ref_que_no_existe_lo_dice(self):
        arbol = nodo("ventana", "App", hijos=[nodo("boton", "Guardar")])
        self._montar(BackendFalso([arbol]))

        with self.assertRaises(ui.ErrorUI) as caso:
            guia.senalar([{"ref": "e77"}])
        self.assertEqual(caso.exception.codigo, "ref_desconocido")

    def test_lo_que_no_ocupa_sitio_ni_llega_a_ser_candidato(self):
        """Un elemento sin rectángulo no se señala porque no está en el árbol.

        Lo quita `ui_tree.podar` antes de llegar aquí, y por eso `senalar` no
        necesita comprobarlo: la primera versión traía esa rama y era código
        muerto.
        """
        arbol = nodo("ventana", "App", hijos=[
            nodo("boton", "Guardar", rect=ui_tree.RECT_NULO),
        ])
        self._montar(BackendFalso([arbol]))

        with self.assertRaises(ui.ErrorUI) as caso:
            guia.senalar([{"rol": "boton", "nombre": "Guardar"}])
        self.assertEqual(caso.exception.codigo, "no_encontrado")

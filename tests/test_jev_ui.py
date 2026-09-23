"""Manejar una ventana con Jev: la poda a 255 hojas y el bucle del servidor.

Sin red y sin máquina. Lo que se prueba es la disciplina —qué se le ofrece,
cuándo se actúa y cuándo se para—, no si Jev acierta.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from app import decisor, jev_ui  # noqa: E402
from vibi_node import ui_tree  # noqa: E402
from vibi_node.ui_tree import Nodo, Rect, Registro  # noqa: E402


def nodo(rol, nombre="", **kwargs):
    kwargs.setdefault("rect", Rect(10, 10, 100, 40))
    hijos = kwargs.pop("hijos", ())
    return Nodo(rol=rol, nombre=nombre, hijos=tuple(hijos), **kwargs)


def numerado(raiz):
    return ui_tree.asignar_refs(raiz, Registro())


class Hojas(TestCase):
    def test_si_caben_salen_todas_y_en_orden(self):
        raiz = numerado(nodo("ventana", "App", hijos=[
            nodo("botón", "Uno"), nodo("botón", "Dos"),
        ]))

        elegidas, total = ui_tree.hojas(raiz)

        self.assertEqual([n.nombre for n in elegidas], ["Uno", "Dos"])
        self.assertEqual(total, 2)

    def test_nunca_pasa_del_tope_y_cuenta_las_que_habia(self):
        raiz = numerado(nodo("ventana", "App", hijos=[
            nodo("celda", f"C{i}") for i in range(400)
        ]))

        elegidas, total = ui_tree.hojas(raiz)

        self.assertEqual(len(elegidas), ui_tree.TOPE_OPCIONES)
        self.assertEqual(total, 400)

    def test_una_tabla_larga_no_deja_fuera_el_boton_de_enviar(self):
        tabla = nodo("tabla", "Mensajes", hijos=[
            nodo("celda", f"M{i}") for i in range(300)
        ])
        raiz = numerado(nodo("ventana", "App", hijos=[
            tabla, nodo("campo", "Escribe un mensaje"), nodo("botón", "Enviar"),
        ]))

        nombres = {n.nombre for n in ui_tree.hojas(raiz, tope=10)[0]}

        self.assertIn("Enviar", nombres)
        self.assertIn("Escribe un mensaje", nombres)

    def test_el_cupo_se_reparte_entre_listas(self):
        """Los primeros de cada lista antes que el trescientos de la larga."""
        larga = nodo("lista", "Larga", hijos=[nodo("opción", f"L{i}") for i in range(50)])
        corta = nodo("lista", "Corta", hijos=[nodo("opción", f"K{i}") for i in range(3)])
        raiz = numerado(nodo("ventana", "App", hijos=[larga, corta]))

        nombres = [n.nombre for n in ui_tree.hojas(raiz, tope=8)[0]]

        self.assertEqual(nombres, ["L0", "L1", "L2", "L3", "L4", "K0", "K1", "K2"])

    def test_los_criterios_salen_de_las_hojas_elegidas(self):
        raiz = numerado(nodo("ventana", "App", hijos=[
            nodo("celda", f"C{i}") for i in range(300)
        ]))
        elegidas, _ = ui_tree.hojas(raiz)

        opciones = ui_tree.criterios(raiz, nodos=elegidas)

        self.assertEqual(len(opciones), ui_tree.TOPE_OPCIONES)


class Acciones(TestCase):
    def test_cada_texto_es_una_opcion_propia(self):
        opciones = jev_ui.acciones(["hola", "adiós"])

        self.assertIn("escribir_1", opciones)
        self.assertIn("escribir_2", opciones)
        self.assertIn("hecho", opciones)

    def test_escribir_lleva_el_texto_que_toca(self):
        paso = jev_ui.paso_de("escribir_2", "e4", ["hola", "adiós"])

        self.assertEqual(paso, {"accion": "escribir", "ref": "e4", "texto": "adiós"})

    def test_intro_no_necesita_elemento(self):
        self.assertEqual(
            jev_ui.paso_de("intro", None, []), {"accion": "tecla", "tecla": "enter"}
        )


VENTANA = {
    "ventana": "WhatsApp",
    "handle": 77,
    "arbol": "[e1] campo \"Escribe\"\n[e2] botón \"Enviar\"",
    "opciones": {"e1": 'campo "Escribe"', "e2": 'botón "Enviar"'},
    "ofrecibles": 2,
}


def respuesta(accion, conf=0.95, elemento=None, conf_el=0.95):
    respuestas = {"accion": decisor.Eleccion(accion, conf, {accion: conf})}
    if elemento:
        respuestas["elemento"] = decisor.Eleccion(elemento, conf_el, {elemento: conf_el})
    return decisor.Respuesta(respuestas=respuestas, ms=400)


class ElBucle(IsolatedAsyncioTestCase):
    def setUp(self):
        for parche in (
            patch.object(decisor, "disponible", return_value=True),
            patch.object(jev_ui.db, "log_event"),
        ):
            parche.start()
            self.addCleanup(parche.stop)
        self.turnos = []

    def nodo_que_responde(self, *estados):
        cola = list(estados)

        async def turno(user, node, argumentos):
            self.turnos.append(argumentos)
            return cola.pop(0) if len(cola) > 1 else cola[0]

        return patch.object(jev_ui, "_turno", side_effect=turno)

    async def manejar(self, *decisiones, estados=(VENTANA,), **kwargs):
        with self.nodo_que_responde(*estados), patch.object(
            decisor, "preguntar", side_effect=list(decisiones)
        ):
            return await jev_ui.manejar(
                {"id": "u1"}, {"id": "n1", "nombre": "PC"},
                "mandar hola a Ana", ["hola"], **kwargs,
            )

    async def test_escribe_envia_y_termina(self):
        ok = {**VENTANA, "paso": {"estado": "ok", "via": "comprobado"}}
        cambiada = {**ok, "arbol": "otra cosa"}
        resultado = await self.manejar(
            respuesta("escribir_1", elemento="e1"),
            respuesta("intro", elemento="e1"),
            respuesta("hecho", elemento="e1"),
            estados=(VENTANA, ok, cambiada),
        )

        self.assertTrue(resultado["terminado"])
        self.assertEqual(
            [t.get("paso") for t in self.turnos[1:]],
            [
                {"accion": "escribir", "ref": "e1", "texto": "hola"},
                {"accion": "tecla", "tecla": "enter"},
            ],
        )
        # La ventana se fija por su identificador desde la primera lectura.
        self.assertEqual(self.turnos[1]["handle"], 77)

    async def test_por_debajo_del_umbral_para_sin_tocar_nada(self):
        resultado = await self.manejar(respuesta("clic", conf=0.4, elemento="e2"))

        self.assertFalse(resultado["terminado"])
        self.assertEqual(resultado["motivo"], "duda")
        self.assertEqual(len(self.turnos), 1)

    async def test_si_duda_del_elemento_tampoco_actua(self):
        resultado = await self.manejar(respuesta("clic", elemento="e2", conf_el=0.5))

        self.assertEqual(resultado["motivo"], "duda")
        self.assertEqual(len(self.turnos), 1)

    async def test_sin_respuesta_de_jev_sigue_el_de_siempre(self):
        resultado = await self.manejar(None)

        self.assertEqual(resultado["motivo"], "sin_decisor")
        self.assertIn("arbol", resultado)

    async def test_un_paso_que_falla_para_el_bucle(self):
        fallo = {**VENTANA, "paso": {"estado": "error", "detalle": "no entró"}}
        resultado = await self.manejar(
            respuesta("escribir_1", elemento="e1"), estados=(VENTANA, fallo)
        )

        self.assertEqual(resultado["motivo"], "error_paso")
        self.assertEqual(resultado["pasos"][0]["error"], "no entró")

    async def test_repetir_lo_mismo_sin_que_cambie_nada_es_estar_atascado(self):
        ok = {**VENTANA, "paso": {"estado": "ok"}}
        resultado = await self.manejar(
            respuesta("clic", elemento="e2"),
            respuesta("clic", elemento="e2"),
            estados=(VENTANA, ok),
        )

        self.assertEqual(resultado["motivo"], "atascado")

    async def test_el_tope_de_pasos_se_respeta(self):
        estados = [VENTANA] + [
            {**VENTANA, "arbol": f"v{i}", "paso": {"estado": "ok"}} for i in range(5)
        ]
        resultado = await self.manejar(
            *[respuesta("clic", elemento="e2") for _ in range(5)],
            estados=estados, max_pasos=3,
        )

        self.assertEqual(resultado["motivo"], "tope_pasos")
        self.assertEqual(len(resultado["pasos"]), 3)

    async def test_sin_clave_ni_se_empieza(self):
        with patch.object(decisor, "disponible", return_value=False):
            with self.assertRaises(jev_ui.JevNoDisponible):
                await jev_ui.manejar({"id": "u"}, {"id": "n"}, "algo")

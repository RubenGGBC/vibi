"""El árbol de accesibilidad: de lo que publica el sistema a lo que lee el modelo.

Todo esto corre sin GUI y sin Windows: `ui_tree` no sabe de plataformas, y esa
es justo la razón de que sea la mayor parte del código.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import ui_tree  # noqa: E402
from vibi_node.ui_tree import Nodo, Rect, Registro, Snapshot  # noqa: E402

VENTANA = Rect(0, 0, 1000, 800)


def nodo(rol, nombre="", **kwargs):
    kwargs.setdefault("rect", Rect(10, 10, 100, 40))
    hijos = kwargs.pop("hijos", ())
    return Nodo(rol=rol, nombre=nombre, hijos=tuple(hijos), **kwargs)


class Poda(TestCase):
    def test_lo_que_cae_fuera_de_la_ventana_no_existe(self):
        dentro = nodo("botón", "Guardar", rect=Rect(10, 10, 100, 40))
        fuera = nodo("botón", "Abajo del todo", rect=Rect(10, 900, 100, 940))
        raiz = nodo("ventana", "App", hijos=[dentro, fuera])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual([h.nombre for h in podado.hijos], ["Guardar"])

    def test_lo_marcado_como_oculto_se_va(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("botón", "Visible"),
            nodo("botón", "Escondido", estado=frozenset({"oculto"})),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual([h.nombre for h in podado.hijos], ["Visible"])

    def test_lo_de_tamano_cero_se_va(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("botón", "Real"),
            nodo("botón", "Sin caja", rect=Rect(50, 50, 50, 50)),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual([h.nombre for h in podado.hijos], ["Real"])

    def test_los_contenedores_anonimos_se_disuelven_y_sus_hijos_suben(self):
        """Los tres `Pane` vacíos que UIA pone alrededor de cada control."""
        raiz = nodo("ventana", "App", hijos=[
            nodo("panel", hijos=[
                nodo("panel", hijos=[
                    nodo("grupo", hijos=[nodo("botón", "Enterrado")]),
                ]),
            ]),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual(len(podado.hijos), 1)
        self.assertEqual(podado.hijos[0].nombre, "Enterrado")

    def test_un_contenedor_con_nombre_se_queda(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("panel", "Barra lateral", hijos=[nodo("botón", "Ir")]),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual(podado.hijos[0].nombre, "Barra lateral")

    def test_un_invisible_no_se_lleva_por_delante_a_sus_hijos_visibles(self):
        """Hay contenedores con rectángulo vacío cuyo contenido sí se ve."""
        raiz = nodo("ventana", "App", hijos=[
            nodo("panel", rect=Rect(0, 0, 0, 0), hijos=[
                nodo("botón", "Sigo aquí", rect=Rect(10, 10, 100, 40)),
            ]),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual([h.nombre for h in podado.hijos], ["Sigo aquí"])

    def test_el_texto_vacio_se_va_pero_el_accionable_sin_nombre_se_queda(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("texto", "   "),
            nodo("campo", ""),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual([h.rol for h in podado.hijos], ["campo"])

    def test_la_etiqueta_que_repite_a_su_padre_se_va(self):
        """Cada pestaña del Bloc de notas colgaba su título otra vez."""
        raiz = nodo("ventana", "App", hijos=[
            nodo("pestaña", "wake.log. No modificado.", hijos=[
                nodo("texto", "wake.log"),
            ]),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual(podado.hijos[0].hijos, ())

    def test_una_etiqueta_que_dice_algo_nuevo_se_queda(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("pestaña", "Resumen", hijos=[
                nodo("texto", "3 archivos sin guardar"),
            ]),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual(len(podado.hijos[0].hijos), 1)

    def test_un_hijo_accionable_nunca_se_considera_redundante(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("pestaña", "wake.log cerrar", hijos=[
                nodo("botón", "cerrar"),
            ]),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual(len(podado.hijos[0].hijos), 1)

    def test_el_separador_decorativo_se_va(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("separador"),
            nodo("botón", "Guardar"),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual([h.rol for h in podado.hijos], ["botón"])


class HermanosRepetidos(TestCase):
    """La misma rama enumerada dos veces por UIA, que no son dos ramas.

    Medido en WhatsApp Desktop el 20/08/2026: su ventana publica el panel
    «WhatsApp» **dos veces, con el mismo runtime id** —`(42, 68252)` las dos—,
    y con él todo lo que cuelga: 71 nodos repetidos de 148. El efecto no es
    solo que el árbol ocupe el doble: **47 de sus 53 nombres salen ambiguos**,
    así que el lote se para a preguntar cuál de los dos campos «Escribir un
    mensaje para Andorra» era, y los dos son el mismo. Sin salida.

    Discord también repite nombres —diecinueve «Texto (limitado)…»— pero con
    identidades distintas: eso sí son elementos distintos y se quedan.
    """

    def test_dos_hermanos_con_la_misma_identidad_se_quedan_en_uno(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("panel", "WhatsApp", identidad=(42, 68252), hijos=[
                nodo("campo", "Escribir un mensaje"),
            ]),
            nodo("panel", "WhatsApp", identidad=(42, 68252), hijos=[
                nodo("campo", "Escribir un mensaje"),
            ]),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual(len(podado.hijos), 1)
        self.assertEqual(ui_tree.contar(podado), 3)

    def test_el_mismo_nombre_con_identidad_distinta_no_se_toca(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("elemento", "Texto (limitado)", identidad=(42, 1)),
            nodo("elemento", "Texto (limitado)", identidad=(42, 2)),
            nodo("elemento", "Texto (limitado)", identidad=(42, 3)),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual(len(podado.hijos), 3)

    def test_sin_identidad_no_se_deduplica_nada(self):
        """Un backend que no publique runtime id no puede perder nodos."""
        raiz = nodo("ventana", "App", hijos=[
            nodo("botón", "Aceptar", identidad=()),
            nodo("botón", "Aceptar", identidad=()),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual(len(podado.hijos), 2)

    def test_la_misma_identidad_en_ramas_distintas_sí_se_queda(self):
        """Solo se comparan hermanos: dos ramas pueden repetir un hijo."""
        raiz = nodo("ventana", "App", hijos=[
            nodo("panel", "Izquierda", identidad=(1,), hijos=[
                nodo("botón", "Aceptar", identidad=(9,)),
            ]),
            nodo("panel", "Derecha", identidad=(2,), hijos=[
                nodo("botón", "Aceptar", identidad=(9,)),
            ]),
        ])

        podado = ui_tree.podar(raiz, VENTANA)[0]

        self.assertEqual(len(podado.hijos), 2)
        self.assertEqual(ui_tree.contar(podado), 5)


class Colapso(TestCase):
    def test_una_lista_larga_deja_muestra_y_cuenta_el_resto(self):
        celdas = [nodo("celda", f"F{i}") for i in range(100)]
        raiz = nodo("ventana", "App", hijos=[nodo("tabla", "Datos", hijos=celdas)])

        colapsado = ui_tree.colapsar(raiz, max_nodos=1000, max_hijos=40)
        tabla = colapsado.hijos[0]

        self.assertEqual(len(tabla.hijos), ui_tree.MUESTRA_HIJOS)
        self.assertEqual(tabla.ocultos, 100 - ui_tree.MUESTRA_HIJOS)

    def test_no_toca_lo_que_ya_cabe(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("botón", f"B{i}") for i in range(10)
        ])

        colapsado = ui_tree.colapsar(raiz, max_nodos=1000, max_hijos=40)

        self.assertEqual(len(colapsado.hijos), 10)
        self.assertEqual(colapsado.ocultos, 0)

    def test_recorta_hasta_caber_en_el_tope_global(self):
        ramas = [
            nodo("grupo", f"G{i}", hijos=[nodo("botón", f"B{i}.{j}") for j in range(30)])
            for i in range(10)
        ]
        raiz = nodo("ventana", "App", hijos=ramas)

        colapsado = ui_tree.colapsar(raiz, max_nodos=50, max_hijos=40)

        self.assertLessEqual(ui_tree.contar(colapsado), 50)

    def test_lo_escondido_queda_contado_y_no_desaparece_en_silencio(self):
        celdas = [nodo("celda", f"F{i}") for i in range(200)]
        raiz = nodo("ventana", "App", hijos=[nodo("tabla", "Datos", hijos=celdas)])

        colapsado = ui_tree.colapsar(raiz, max_nodos=30, max_hijos=40)

        escondidos = sum(n.ocultos for n in ui_tree.recorrer_todos(colapsado))
        vistos = ui_tree.contar(colapsado)
        # Nada se pierde: lo que no se ve, se cuenta.
        self.assertEqual(escondidos + vistos, 202)


class Refs(TestCase):
    def setUp(self):
        self.registro = Registro()

    def test_solo_lo_accionable_gasta_un_ref(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("texto", "Solo informa"),
            nodo("botón", "Pulsa"),
        ])

        numerado = ui_tree.asignar_refs(raiz, self.registro)

        self.assertIsNone(numerado.hijos[0].ref)
        self.assertEqual(numerado.hijos[1].ref, "e1")

    def test_lo_colapsado_se_numera_para_poder_pedirlo(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("panel", "Tareas", ocultos=340),
        ])

        numerado = ui_tree.asignar_refs(raiz, self.registro)

        self.assertEqual(numerado.hijos[0].ref, "e1")

    def test_los_refs_van_en_orden_de_lectura(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("botón", "Primero"),
            nodo("grupo", "G", hijos=[nodo("botón", "Segundo")]),
            nodo("botón", "Tercero"),
        ])

        numerado = ui_tree.asignar_refs(raiz, self.registro)
        nombres = {
            n.ref: n.nombre for n in ui_tree.recorrer_todos(numerado) if n.ref
        }

        # «G» también se numera: es un contenedor con nombre, y por tanto un
        # ámbito válido para acotar una búsqueda con `dentro_de`. La ventana
        # no, porque no llega a pintarse.
        self.assertEqual(nombres, {
            "e1": "Primero", "e2": "G", "e3": "Segundo", "e4": "Tercero",
        })

    def test_la_ventana_no_gasta_ref_porque_no_se_pinta(self):
        raiz = nodo("ventana", "App", hijos=[nodo("botón", "Único")])

        numerado = ui_tree.asignar_refs(raiz, self.registro)

        self.assertIsNone(numerado.ref)
        self.assertEqual(numerado.hijos[0].ref, "e1")

    def test_un_contenedor_con_nombre_se_numera_para_poder_acotar(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("panel", "Diálogo", hijos=[nodo("botón", "Aceptar")]),
        ])

        numerado = ui_tree.asignar_refs(raiz, self.registro)

        self.assertIsNotNone(numerado.hijos[0].ref)

    def test_un_contenedor_sin_nombre_no_gasta_ref(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("panel", "", hijos=[nodo("botón", "Aceptar")]),
        ])

        numerado = ui_tree.asignar_refs(raiz, self.registro)

        self.assertIsNone(numerado.hijos[0].ref)

    def test_un_snapshot_nuevo_invalida_los_refs_del_anterior(self):
        primera = nodo("ventana", "App", hijos=[nodo("botón", "Viejo")])
        ui_tree.asignar_refs(primera, self.registro)
        self.assertIn("e1", self.registro)

        segunda = nodo("ventana", "App", hijos=[])
        ui_tree.asignar_refs(segunda, self.registro)

        self.assertNotIn("e1", self.registro)

    def test_el_registro_guarda_la_huella_para_revalidar(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("botón", "Guardar", identidad=(7, 42)),
        ])

        ui_tree.asignar_refs(raiz, self.registro)
        _, huella = self.registro.obtener("e1")

        self.assertEqual(huella.rol, "botón")
        self.assertEqual(huella.nombre, "Guardar")
        self.assertEqual(huella.identidad, (7, 42))


class Busqueda(TestCase):
    def setUp(self):
        self.registro = Registro()
        crudo = nodo("ventana", "App", hijos=[
            nodo("menú", "Archivo"),
            nodo("botón", "Guardar"),
            nodo("botón", "Guardar como"),
            nodo("panel", "Diálogo", hijos=[
                nodo("botón", "Aceptar"),
                nodo("campo", "Nombre de archivo"),
            ]),
            nodo("botón", "Aceptar"),
        ])
        self.raiz = ui_tree.asignar_refs(crudo, self.registro)

    def test_el_nombre_exacto_gana_al_que_solo_contiene(self):
        encontrados = ui_tree.buscar(self.raiz, nombre="Guardar")

        self.assertEqual([n.nombre for n in encontrados], ["Guardar"])

    def test_sin_exacto_cae_a_contiene(self):
        encontrados = ui_tree.buscar(self.raiz, nombre="Guardar co")

        self.assertEqual([n.nombre for n in encontrados], ["Guardar como"])

    def test_ignora_acentos_y_mayusculas(self):
        encontrados = ui_tree.buscar(self.raiz, nombre="DIALOGO")

        self.assertEqual([n.nombre for n in encontrados], ["Diálogo"])

    def test_el_rol_filtra_antes_que_el_nombre(self):
        encontrados = ui_tree.buscar(self.raiz, rol="menú", nombre="Archivo")

        self.assertEqual(len(encontrados), 1)
        self.assertEqual(encontrados[0].rol, "menú")

    def test_devuelve_todos_los_candidatos_sin_elegir(self):
        """Dos «Aceptar» son una ambigüedad, no una elección de la búsqueda."""
        encontrados = ui_tree.buscar(self.raiz, nombre="Aceptar")

        self.assertEqual(len(encontrados), 2)

    def test_dentro_de_acota_al_subarbol(self):
        dialogo = next(
            n for n in ui_tree.recorrer_todos(self.raiz) if n.nombre == "Diálogo"
        )
        encontrados = ui_tree.buscar(
            self.raiz, nombre="Aceptar", dentro_de=dialogo.ref
        )

        self.assertEqual(len(encontrados), 1)

    def test_un_dentro_de_que_no_existe_no_encuentra_nada(self):
        self.assertEqual(ui_tree.buscar(self.raiz, nombre="Aceptar", dentro_de="e99"), [])


class Render(TestCase):
    def setUp(self):
        self.registro = Registro()

    def _pintar(self, raiz, **kwargs):
        numerado = ui_tree.asignar_refs(raiz, self.registro)
        snapshot = Snapshot(
            ventana=kwargs.pop("ventana", "App"),
            otras_ventanas=kwargs.pop("otras", ()),
            raiz=numerado,
            totales=ui_tree.contar(numerado),
            **kwargs,
        )
        return ui_tree.render(snapshot)

    def test_la_jerarquia_se_ve_en_la_indentacion(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("tabla", "Hoja1", hijos=[nodo("celda", "A1")]),
        ])

        texto = self._pintar(raiz)

        self.assertIn('tabla "Hoja1"', texto)
        self.assertIn('  celda "A1"', texto)
        # La celda va sangrada un nivel por debajo de su tabla.
        sangria = {
            linea.split("]")[-1].index("t"): None
            for linea in texto.splitlines() if "tabla" in linea
        }
        self.assertTrue(sangria)

    def test_el_valor_sale_cuando_lo_hay(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("campo", "Nombre", valor="Rubén"),
        ])

        self.assertIn('campo "Nombre" = "Rubén"', self._pintar(raiz))

    def test_los_estados_salen_entre_parentesis(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("casilla", "Recordarme", estado=frozenset({"marcado"})),
        ])

        self.assertIn("(marcado)", self._pintar(raiz))

    def test_lo_colapsado_dice_cuanto_esconde_y_como_pedirlo(self):
        raiz = nodo("ventana", "App", hijos=[
            nodo("panel", "Tareas", ocultos=340),
        ])

        texto = self._pintar(raiz)

        self.assertIn("+340 dentro", texto)
        self.assertIn("pide e1", texto)

    def test_siempre_dice_cuantos_nodos_omitio(self):
        raiz = nodo("ventana", "App", hijos=[nodo("botón", "Solo")])

        texto = self._pintar(raiz, omitidos=1973)

        self.assertIn("1973 omitidos", texto)

    def test_la_cabecera_lista_las_otras_ventanas(self):
        raiz = nodo("ventana", "Excel", hijos=[nodo("botón", "B")])

        texto = self._pintar(raiz, ventana="Excel", otras=("Chrome", "Discord"))

        self.assertIn('ventana con foco: "Excel"', texto)
        self.assertIn("otras ventanas: Chrome, Discord", texto)

    def test_un_arbol_vacio_manda_a_la_captura(self):
        snapshot = Snapshot(
            ventana="Discord", otras_ventanas=(), raiz=None
        )

        texto = ui_tree.render(snapshot)

        self.assertIn("no publica árbol de accesibilidad", texto)
        self.assertIn("devices_screenshot", texto)


class Roles(TestCase):
    def test_windows_y_macos_hablan_el_mismo_vocabulario(self):
        """El mismo prompt tiene que funcionar en las dos plataformas."""
        self.assertEqual(ui_tree.rol_uia(50000), "botón")
        self.assertEqual(ui_tree.rol_ax("AXButton"), "botón")
        self.assertEqual(ui_tree.rol_uia(50004), "campo")
        self.assertEqual(ui_tree.rol_ax("AXTextField"), "campo")

    def test_lo_desconocido_no_revienta(self):
        self.assertEqual(ui_tree.rol_uia(99999), "elemento")
        self.assertEqual(ui_tree.rol_ax("AXLoQueSea"), "elemento")

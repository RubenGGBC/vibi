"""El motor de lotes: resolver cada paso contra el árbol vivo y parar al fallo.

Con un backend de mentira, porque lo que se prueba aquí es la disciplina del
lote —cuándo para, qué devuelve, cómo desambigua— y no si UIA sabe pulsar un
botón. Eso último solo lo puede decir una máquina con ventanas de verdad.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import ui, ui_tree  # noqa: E402
from vibi_node.ui_tree import Nodo, Rect  # noqa: E402

VENTANA = Rect(0, 0, 1000, 800)


def nodo(rol, nombre="", **kwargs):
    kwargs.setdefault("rect", Rect(10, 10, 100, 40))
    kwargs.setdefault("nativo", object())
    hijos = kwargs.pop("hijos", ())
    return Nodo(rol=rol, nombre=nombre, hijos=tuple(hijos), **kwargs)


class BackendFalso:
    """Un escritorio de mentira que apunta lo que le piden."""

    def __init__(self, arboles):
        # Una lista: cada lectura consume el siguiente, y el último se repite.
        self.arboles = list(arboles)
        self.hechas: list[tuple[str, str]] = []
        self.vivos = True
        self.lecturas = 0

    # --- lectura ---
    def capturar(self, ventana=None):
        indice = min(self.lecturas, len(self.arboles) - 1)
        self.lecturas += 1
        return self.arboles[indice], VENTANA, "App", ("Otra",), None

    def sigue_vivo(self, nativo, huella):
        return self.vivos

    # --- acciones ---
    def _apuntar(self, accion, elemento):
        self.hechas.append((accion, getattr(elemento, "etiqueta", "?")))
        return f"patrón {accion}"

    def clic(self, elemento, boton="left", veces=1):
        return self._apuntar("clic", elemento)

    def escribir(self, elemento, texto):
        self.hechas.append(("escribir", texto))
        return "patrón valor"

    def seleccionar(self, elemento):
        return self._apuntar("seleccionar", elemento)

    def expandir(self, elemento):
        return self._apuntar("expandir", elemento)

    def contraer(self, elemento):
        return self._apuntar("contraer", elemento)

    def enfocar(self, elemento):
        self._apuntar("enfocar", elemento)

    def disponible(self):
        return True


class Marcado:
    def __init__(self, etiqueta):
        self.etiqueta = etiqueta


def arbol(*hijos):
    return nodo("ventana", "App", hijos=hijos)


class BaseLote(TestCase):
    def setUp(self):
        ui.olvidar()
        self.addCleanup(ui.olvidar)
        # Sin esperas: lo que se prueba es la lógica, no el reloj.
        parche = patch.object(ui, "ESPERA_ASENTAR", 0)
        parche.start()
        self.addCleanup(parche.stop)

    def montar(self, *arboles):
        backend = BackendFalso(arboles)
        parche = patch.object(ui, "_backend", return_value=backend)
        parche.start()
        self.addCleanup(parche.stop)
        return backend


class Validacion(BaseLote):
    def test_un_lote_vacio_no_se_acepta(self):
        self.montar(arbol(nodo("botón", "A")))

        with self.assertRaises(ui.ErrorUI) as caso:
            ui.ejecutar_lote([])

        self.assertEqual(caso.exception.codigo, "lote_vacio")

    def test_un_lote_demasiado_largo_no_se_acepta(self):
        self.montar(arbol(nodo("botón", "A")))
        pasos = [{"accion": "tecla", "tecla": "a"}] * (ui.MAX_PASOS + 1)

        with self.assertRaises(ui.ErrorUI) as caso:
            ui.ejecutar_lote(pasos)

        self.assertEqual(caso.exception.codigo, "lote_largo")

    def test_una_accion_que_no_existe_se_rechaza_antes_de_tocar_nada(self):
        backend = self.montar(arbol(nodo("botón", "A")))

        with self.assertRaises(ui.ErrorUI) as caso:
            ui.ejecutar_lote([
                {"accion": "clic", "buscar": {"nombre": "A"}},
                {"accion": "bailar"},
            ])

        self.assertEqual(caso.exception.codigo, "accion_desconocida")
        # Y no se ha ejecutado el primer paso, que sí era válido.
        self.assertEqual(backend.hechas, [])


class Ejecucion(BaseLote):
    def test_una_secuencia_entera_en_una_sola_llamada(self):
        backend = self.montar(arbol(
            nodo("campo", "Nombre", nativo=Marcado("campo")),
            nodo("botón", "Aceptar", nativo=Marcado("aceptar")),
        ))

        resultado = ui.ejecutar_lote([
            {"accion": "escribir", "buscar": {"nombre": "Nombre"},
             "texto": "Rubén"},
            {"accion": "clic", "buscar": {"nombre": "Aceptar"}},
        ])

        self.assertIsNone(resultado["error"])
        self.assertEqual(resultado["completados"], 2)
        self.assertEqual(
            backend.hechas, [("escribir", "Rubén"), ("clic", "aceptar")]
        )

    def test_un_paso_puede_apuntar_a_lo_que_aun_no_existe(self):
        """El menú se abre en el paso 1 y su opción solo existe en el 2."""
        cerrado = arbol(nodo("menú", "Archivo", nativo=Marcado("archivo")))
        abierto = arbol(
            nodo("menú", "Archivo", nativo=Marcado("archivo"), hijos=[
                nodo("opción", "Guardar como", nativo=Marcado("guardar")),
            ]),
        )
        backend = self.montar(cerrado, abierto)

        resultado = ui.ejecutar_lote([
            {"accion": "clic", "buscar": {"nombre": "Archivo"}},
            {"accion": "clic", "buscar": {"nombre": "Guardar como"}},
        ])

        self.assertIsNone(resultado["error"])
        self.assertEqual(
            backend.hechas, [("clic", "archivo"), ("clic", "guardar")]
        )

    def test_la_tecla_no_necesita_objetivo(self):
        self.montar(arbol(nodo("botón", "A")))

        with patch.object(ui, "_actuar", return_value="teclado") as actuar:
            resultado = ui.ejecutar_lote([{"accion": "tecla", "tecla": "enter"}])

        self.assertIsNone(resultado["error"])
        self.assertIsNone(actuar.call_args[0][2])

    def test_el_arbol_final_viene_siempre(self):
        self.montar(arbol(nodo("botón", "A", nativo=Marcado("a"))))

        resultado = ui.ejecutar_lote([
            {"accion": "clic", "buscar": {"nombre": "A"}},
        ])

        self.assertIn("ventana con foco", resultado["arbol"])

    def test_un_snapshot_en_medio_deja_su_arbol_en_su_paso(self):
        self.montar(arbol(nodo("botón", "A", nativo=Marcado("a"))))

        resultado = ui.ejecutar_lote([
            {"accion": "snapshot"},
            {"accion": "clic", "buscar": {"nombre": "A"}},
        ])

        self.assertIn("arbol", resultado["pasos"][0])
        self.assertNotIn("arbol", resultado["pasos"][1])


class LoQuePideElModeloDeVerdad(BaseLote):
    """Los tres casos que el modelo pidió y la API le rechazaba.

    Salieron de mirar un turno real: le encargaron mandar un WhatsApp, el
    lote le rechazó estas tres cosas seguidas y acabó operando a base de
    capturas. Ninguna era un capricho.
    """

    def test_esperar_sin_buscar_es_una_pausa(self):
        self.montar(arbol(nodo("botón", "A", nativo=Marcado("a"))))

        resultado = ui.ejecutar_lote([
            {"accion": "tecla", "tecla": "ctrl+f"},
            {"accion": "esperar", "timeout_ms": 200},
            {"accion": "clic", "buscar": {"nombre": "A"}},
        ])

        self.assertIsNone(resultado["error"], resultado["pasos"])
        self.assertIn("pausa", resultado["pasos"][1]["via"])

    def test_una_pausa_no_se_come_el_lote_entero(self):
        self.montar(arbol(nodo("botón", "A")))

        resultado = ui.ejecutar_lote([
            {"accion": "esperar", "timeout_ms": 30_000},
        ])

        self.assertIsNone(resultado["error"])
        # Recortada a MAX_PAUSA, no los 30 s que pedía.
        self.assertLess(resultado["ms"], ui.MAX_PAUSA * 1000 + 2000)

    def test_escribir_sin_objetivo_va_donde_este_el_foco(self):
        """«Enfoca esto y escribe» es como funciona un teclado."""
        backend = self.montar(arbol(nodo("campo", "Buscar", nativo=Marcado("campo"))))

        with patch.object(ui, "_actuar", wraps=ui._actuar) as actuar:
            resultado = ui.ejecutar_lote([
                {"accion": "enfocar", "buscar": {"nombre": "Buscar"}},
                {"accion": "escribir", "texto": "Ruffini"},
            ])

        self.assertIsNone(resultado["error"], resultado["pasos"])
        self.assertEqual(backend.hechas[0], ("enfocar", "campo"))
        # El segundo paso no llevaba objetivo y aun así se ejecutó.
        self.assertIsNone(actuar.call_args_list[1][0][2])

    def test_escribir_con_objetivo_sigue_yendo_al_elemento(self):
        backend = self.montar(arbol(nodo("campo", "Buscar", nativo=Marcado("campo"))))

        resultado = ui.ejecutar_lote([
            {"accion": "escribir", "buscar": {"nombre": "Buscar"},
             "texto": "Ruffini"},
        ])

        self.assertIsNone(resultado["error"])
        self.assertEqual(backend.hechas, [("escribir", "Ruffini")])

    def test_lo_que_si_necesita_objetivo_lo_sigue_exigiendo(self):
        self.montar(arbol(nodo("botón", "A")))

        resultado = ui.ejecutar_lote([{"accion": "clic"}])

        self.assertEqual(resultado["error"], "falta_objetivo")


class Parada(BaseLote):
    def test_para_al_primer_fallo_y_no_sigue(self):
        backend = self.montar(arbol(
            nodo("botón", "Primero", nativo=Marcado("primero")),
            nodo("botón", "Tercero", nativo=Marcado("tercero")),
        ))

        resultado = ui.ejecutar_lote([
            {"accion": "clic", "buscar": {"nombre": "Primero"}},
            {"accion": "clic", "buscar": {"nombre": "No existe"}},
            {"accion": "clic", "buscar": {"nombre": "Tercero"}},
        ])

        self.assertEqual(resultado["error"], "no_encontrado")
        self.assertEqual(resultado["completados"], 1)
        self.assertEqual(len(resultado["pasos"]), 2)
        # El tercero no llegó a ejecutarse.
        self.assertEqual(backend.hechas, [("clic", "primero")])

    def test_varios_candidatos_paran_el_lote_en_vez_de_elegir(self):
        backend = self.montar(arbol(
            nodo("botón", "Aceptar", nativo=Marcado("uno")),
            nodo("botón", "Aceptar", nativo=Marcado("dos")),
        ))

        resultado = ui.ejecutar_lote([
            {"accion": "clic", "buscar": {"nombre": "Aceptar"}},
        ])

        self.assertEqual(resultado["error"], "ambiguo")
        self.assertEqual(backend.hechas, [])

    def test_dentro_de_desambigua_lo_que_era_ambiguo(self):
        backend = self.montar(arbol(
            nodo("botón", "Aceptar", nativo=Marcado("suelto")),
            nodo("panel", "Guardar como", hijos=[
                nodo("botón", "Aceptar", nativo=Marcado("del diálogo")),
            ]),
        ))

        # Primero se localiza el ámbito, y después se acota con su ref.
        vista = ui.capturar()
        ref = next(
            linea.split("]")[0].strip("[")
            for linea in vista["arbol"].splitlines()
            if "Guardar como" in linea
        )
        resultado = ui.ejecutar_lote([
            {"accion": "clic",
             "buscar": {"nombre": "Aceptar", "dentro_de": ref}},
        ])

        self.assertIsNone(resultado["error"])
        self.assertEqual(backend.hechas, [("clic", "del diálogo")])

    def test_un_ref_que_ya_no_senala_lo_mismo_para_el_lote(self):
        backend = self.montar(arbol(nodo("botón", "Guardar", nativo=Marcado("g"))))
        vista = ui.capturar()
        self.assertIn("[e1]", vista["arbol"])

        backend.vivos = False
        resultado = ui.ejecutar_lote([{"accion": "clic", "ref": "e1"}])

        self.assertEqual(resultado["error"], "ref_caducado")
        self.assertEqual(backend.hechas, [])

    def test_un_ref_de_otra_epoca_se_dice_claramente(self):
        self.montar(arbol(nodo("botón", "A", nativo=Marcado("a"))))

        resultado = ui.ejecutar_lote([{"accion": "clic", "ref": "e99"}])

        self.assertEqual(resultado["error"], "ref_desconocido")

    def test_un_paso_sin_objetivo_se_queja(self):
        self.montar(arbol(nodo("botón", "A")))

        resultado = ui.ejecutar_lote([{"accion": "clic"}])

        self.assertEqual(resultado["error"], "falta_objetivo")

    def test_el_presupuesto_agotado_devuelve_lo_hecho(self):
        self.montar(arbol(nodo("botón", "A", nativo=Marcado("a"))))

        with patch.object(ui, "PRESUPUESTO", -1):
            resultado = ui.ejecutar_lote([
                {"accion": "clic", "buscar": {"nombre": "A"}},
            ])

        self.assertEqual(resultado["error"], "presupuesto_agotado")
        self.assertIn("arbol", resultado)


class Espera(BaseLote):
    def test_esperar_encuentra_lo_que_tarda_en_aparecer(self):
        vacio = arbol(nodo("texto", "Cargando"))
        listo = arbol(nodo("botón", "Listo", nativo=Marcado("listo")))
        self.montar(vacio, listo)

        resultado = ui.ejecutar_lote([
            {"accion": "esperar", "buscar": {"nombre": "Listo"},
             "timeout_ms": 3000},
        ])

        self.assertIsNone(resultado["error"])
        self.assertIn("apareció", resultado["pasos"][0]["via"])

    def test_esperar_se_rinde_y_lo_dice(self):
        self.montar(arbol(nodo("texto", "Cargando")))

        with patch.object(ui, "ESPERA_BUSQUEDA", 0.05):
            resultado = ui.ejecutar_lote([
                {"accion": "esperar", "buscar": {"nombre": "Nunca"}},
            ])

        self.assertEqual(resultado["error"], "no_encontrado")


class Captura(BaseLote):
    def test_un_arbol_sin_nada_se_marca_como_vacio(self):
        self.montar(nodo("ventana", "Discord", rect=Rect(0, 0, 0, 0)))

        vista = ui.capturar()

        self.assertTrue(vista["vacio"])

    def test_expandir_acota_al_subarbol_pedido(self):
        self.montar(arbol(
            nodo("panel", "Lateral", hijos=[nodo("botón", "Dentro")]),
            nodo("botón", "Fuera"),
        ))
        vista = ui.capturar()
        ref = next(
            linea.split("]")[0].strip("[")
            for linea in vista["arbol"].splitlines()
            if "Lateral" in linea
        )

        acotada = ui.capturar(expandir=ref)

        self.assertIn("Dentro", acotada["arbol"])
        self.assertNotIn("Fuera", acotada["arbol"])

    def test_un_expandir_inventado_se_dice(self):
        self.montar(arbol(nodo("botón", "A")))

        with self.assertRaises(ui.ErrorUI) as caso:
            ui.capturar(expandir="e77")

        self.assertEqual(caso.exception.codigo, "ref_desconocido")

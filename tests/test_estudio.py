"""El engine de Estudio: fórmulas, algoritmos, física y el ciclo de las herramientas."""
import asyncio
import json
import math
import tempfile
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import auth, db, tools
from app.config import settings
from app.estudio import (
    algoritmos, atlas, biblioteca, capturas, composicion, escena, fisica, modelos, moleculas, primitivas,
    generacion,
    sketchfab,
    urdf,
)
from app.estudio.expresiones import ExpresionInvalida, compilar


class Expresiones(TestCase):
    def test_la_forma_canonica_usa_el_circunflejo(self):
        self.assertEqual(compilar("x**2 + 1", {"x"}).fuente, "x ^ 2 + 1")
        self.assertEqual(compilar("x^2", {"x"}).fuente, "x ^ 2")

    def test_evalua_con_funciones_y_constantes(self):
        expresion = compilar("sin(pi*x/2) + ln(e)", {"x"})
        self.assertAlmostEqual(expresion.evaluar({"x": 1}), 2.0)

    def test_fuera_del_dominio_es_nan_y_no_una_excepcion(self):
        self.assertTrue(math.isnan(compilar("1/x", {"x"}).evaluar({"x": 0})))
        self.assertTrue(math.isnan(compilar("sqrt(x)", {"x"}).evaluar({"x": -1})))
        self.assertTrue(math.isnan(compilar("(-8)^(1/3)", set()).evaluar({})))

    def test_una_potencia_enorme_no_cuelga_el_servidor(self):
        self.assertTrue(math.isnan(compilar("10^10^10", set()).evaluar({})))

    def test_rechaza_lo_que_no_es_una_formula(self):
        for texto in (
            "__import__('os')",
            "x.real",
            "[1, 2]",
            "lambda: 1",
            "x if x else 1",
            "x % 2",
            "'texto'",
            "True",
            "foo(x)",
        ):
            with self.subTest(texto=texto), self.assertRaises(ExpresionInvalida):
                compilar(texto, {"x"})

    def test_un_nombre_no_declarado_dice_como_arreglarlo(self):
        with self.assertRaises(ExpresionInvalida) as error:
            compilar("a*x", {"x"})
        self.assertIn("estudio_parametro", str(error.exception))

    def test_producto_implicito_explica_la_sintaxis(self):
        with self.assertRaises(ExpresionInvalida) as error:
            compilar("2x", {"x"})
        self.assertIn("2*x", str(error.exception))

    def test_registra_las_variables_que_usa(self):
        self.assertEqual(compilar("a*sin(k*x)", {"x", "a", "k", "b"}).variables, {"a", "k", "x"})


class Algoritmos(TestCase):
    NODOS = ["A", "B", "C", "D", "E"]
    ARISTAS = [
        {"desde": "A", "hasta": "B", "peso": 4},
        {"desde": "A", "hasta": "C", "peso": 1},
        {"desde": "C", "hasta": "B", "peso": 2},
        {"desde": "B", "hasta": "D", "peso": 1},
        {"desde": "C", "hasta": "D", "peso": 5},
        {"desde": "D", "hasta": "E", "peso": 3},
    ]

    def test_dijkstra_encuentra_el_camino_mas_corto(self):
        ejecucion = algoritmos.recorrer("dijkstra", self.NODOS, self.ARISTAS, False, "A", "E")
        resultado = ejecucion["resultado"]
        self.assertEqual(resultado["camino"], ["A", "C", "B", "D", "E"])
        self.assertEqual(resultado["coste"], 7)
        self.assertEqual(ejecucion["fotogramas"][-1]["camino"], resultado["camino"])

    def test_bfs_minimiza_aristas(self):
        resultado = algoritmos.recorrer("bfs", self.NODOS, self.ARISTAS, False, "A", "E")["resultado"]
        self.assertEqual(len(resultado["camino"]) - 1, 3)
        self.assertEqual(resultado["camino"][0], "A")
        self.assertEqual(resultado["camino"][-1], "E")

    def test_dfs_sigue_el_arbol_que_recorre(self):
        resultado = algoritmos.recorrer("dfs", self.NODOS, self.ARISTAS, False, "A", None)["resultado"]
        self.assertEqual(resultado["orden_de_visita"], ["A", "B", "C", "D", "E"])

    def test_sin_camino_lo_dice(self):
        resultado = algoritmos.recorrer(
            "dijkstra", ["A", "B"], [], False, "A", "B"
        )["resultado"]
        self.assertEqual(resultado["camino"], [])

    def test_dijkstra_rechaza_pesos_negativos(self):
        with self.assertRaises(algoritmos.AlgoritmoInvalido):
            algoritmos.recorrer(
                "dijkstra", ["A", "B"], [{"desde": "A", "hasta": "B", "peso": -1}], False, "A", None
            )

    def test_todas_las_ordenaciones_ordenan(self):
        valores = algoritmos.valores_aleatorios(25, 3)
        for nombre in algoritmos.ALGORITMOS_ORDENACION:
            with self.subTest(nombre=nombre):
                ejecucion = algoritmos.ordenar(nombre, valores)
                self.assertEqual(ejecucion["resultado"]["ordenado"], sorted(valores))
                self.assertEqual(ejecucion["fotogramas"][-1]["valores"], sorted(valores))
                self.assertGreater(ejecucion["resultado"]["comparaciones"], 0)

    def test_burbuja_sobre_algo_ordenado_hace_una_pasada(self):
        resultado = algoritmos.ordenar("burbuja", [1, 2, 3, 4, 5])["resultado"]
        self.assertEqual(resultado["comparaciones"], 4)
        self.assertEqual(resultado["escrituras"], 0)


class Fisica(TestCase):
    def test_el_periodo_real_tiende_al_de_pequenas_oscilaciones(self):
        datos = fisica.magnitudes(
            "pendulo",
            {"longitud": 1, "gravedad": 9.81, "angulo_inicial": 2, "amortiguamiento": 0},
        )
        self.assertAlmostEqual(
            datos["periodo_real_s"], datos["periodo_pequenas_oscilaciones_s"], places=2
        )

    def test_a_noventa_grados_el_periodo_es_un_18_por_ciento_mayor(self):
        datos = fisica.magnitudes(
            "pendulo",
            {"longitud": 1, "gravedad": 9.81, "angulo_inicial": 90, "amortiguamiento": 0},
        )
        self.assertAlmostEqual(
            datos["periodo_real_s"] / datos["periodo_pequenas_oscilaciones_s"], 1.18, places=2
        )

    def test_alcance_del_proyectil(self):
        datos = fisica.magnitudes(
            "proyectil", {"velocidad": 20, "angulo": 30, "gravedad": 9.81, "altura_inicial": 0}
        )
        self.assertAlmostEqual(
            datos["alcance_m"], 20**2 * math.sin(math.radians(60)) / 9.81, places=1
        )

    def test_parametros_fuera_de_rango(self):
        with self.assertRaises(fisica.SimulacionInvalida):
            fisica.resolver_parametros(fisica.MODELOS["pendulo"], {"longitud": 500})
        with self.assertRaises(fisica.SimulacionInvalida):
            fisica.resolver_parametros(fisica.MODELOS["pendulo"], {"masa": 1})


SDF_AGUA = """962
  -OEChem-10222600003D

  3  2  0     0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
    0.2774    0.8929    0.2544 H   0  0  0  0  0  0  0  0  0  0  0  0
    0.6068   -0.2383   -0.7169 H   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0  0  0  0
  1  3  1  0  0  0  0
M  END
$$$$
"""


class Moleculas(TestCase):
    def test_lee_un_sdf_de_pubchem(self):
        atomos, enlaces = moleculas.parsear_sdf(SDF_AGUA)
        self.assertEqual([a["elemento"] for a in atomos], ["O", "H", "H"])
        self.assertEqual(enlaces[1], {"a": 0, "b": 2, "orden": 1})
        self.assertEqual(moleculas.formula_de(atomos), "H2O")

    def test_formula_de_hill(self):
        atomos = [{"elemento": e} for e in ["O", "C", "H", "H", "C", "N"]]
        self.assertEqual(moleculas.formula_de(atomos), "C2H2NO")

    def test_el_agua_local_tiene_su_angulo(self):
        agua = moleculas.local("agua")
        o, h1, h2 = (a["posicion"] for a in agua["atomos"])
        v1 = [a - b for a, b in zip(h1, o)]
        v2 = [a - b for a, b in zip(h2, o)]
        coseno = sum(a * b for a, b in zip(v1, v2)) / (
            math.dist(h1, o) * math.dist(h2, o)
        )
        self.assertAlmostEqual(math.degrees(math.acos(coseno)), 104.5, places=1)

    def test_el_amoniaco_local_tiene_su_angulo(self):
        amoniaco = moleculas.local("NH3")
        n, h1, h2, _ = (a["posicion"] for a in amoniaco["atomos"])
        v1 = [a - b for a, b in zip(h1, n)]
        v2 = [a - b for a, b in zip(h2, n)]
        coseno = sum(a * b for a, b in zip(v1, v2)) / (math.dist(h1, n) * math.dist(h2, n))
        self.assertAlmostEqual(math.degrees(math.acos(coseno)), 106.7, places=1)


class _ConUsuario(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        for parche in (
            patch.object(settings, "db_path", str(root / "vibi.db")),
            patch.object(settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"),
        ):
            parche.start()
            self.addCleanup(parche.stop)
        db.init_db()
        escena.olvidar_cache()
        self.addCleanup(escena.olvidar_cache)
        self.user = db.get_or_create_user("ana")
        self.enviados = []

        async def enviar(user_id, payload):
            self.enviados.append(payload)

        envio = patch.object(escena.events.manager, "send", side_effect=enviar)
        envio.start()
        self.addCleanup(envio.stop)

    async def run_tool(self, tool_id, **argumentos):
        return (await tools.execute(tool_id, self.user, argumentos))["result"]


class Herramientas(_ConUsuario):
    async def test_la_serie_armonica_de_principio_a_fin(self):
        await self.run_tool("estudio.nueva_escena", titulo="La serie armónica", rango_x=[0, 50], rango_y=[0, 5])
        await self.run_tool("estudio.parametro", id="N", etiqueta="Términos", minimo=1, maximo=50, valor=10)
        terminos = await self.run_tool("estudio.sucesion", expresion="1/n", hasta="N", id="terminos")
        sumas = await self.run_tool(
            "estudio.sucesion", expresion="1/n", hasta="N", acumulada=True, estilo="linea", id="sumas"
        )
        aproximacion = await self.run_tool(
            "estudio.funcion", expresion="ln(x) + 0.5772", id="log", desde=1, hasta=50
        )
        await self.run_tool(
            "estudio.paso", texto="Cada término es más pequeño", idea="Los términos tienden a 0",
            mostrar=["terminos"],
        )
        segundo = await self.run_tool(
            "estudio.paso", texto="Pero la suma sigue creciendo", idea="La suma no se frena",
            mostrar=["sumas"],
        )
        tercero = await self.run_tool(
            "estudio.paso",
            texto="Crece como el logaritmo",
            idea="Crece como ln(N), sin techo",
            mostrar=["log"],
            pregunta={
                "enunciado": "¿Converge la serie?",
                "opciones": ["Sí", "No"],
                "correcta": 1,
                "explicacion": "Las sumas crecen como ln(N) sin límite",
            },
        )

        self.assertEqual(terminos["primeros_terminos"][:3], [1.0, 0.5, 0.333333])
        self.assertAlmostEqual(sumas["suma_parcial_hasta_el_ultimo"], 2.92897, places=4)
        self.assertEqual(aproximacion["avisos"], [])
        self.assertEqual(segundo["numero"], 2)
        self.assertEqual(tercero["se_ve_en_este_paso"], ["log", "sumas", "terminos"])
        # Con los tres pasos puestos, cada elemento aparece en el suyo.
        final = escena.cargar(self.user["id"])
        self.assertEqual(escena.visibles_en(final, 0), {"terminos"})
        self.assertEqual(escena.visibles_en(final, 1), {"terminos", "sumas"})

        revision = await self.run_tool("estudio.validar")
        self.assertTrue(revision["ok"], revision)
        self.assertEqual(revision["avisos"], [])

        ultima = self.enviados[-1]
        self.assertEqual(ultima["tipo"], "estudio_escena")
        self.assertEqual(len(ultima["escena"]["elementos"]), 3)
        self.assertEqual(ultima["escena"]["elementos"][0]["procedencia"]["origen"], "engine")

    async def test_una_herramienta_que_falla_no_deja_la_escena_a_medias(self):
        await self.run_tool("estudio.nueva_escena", titulo="Prueba")
        version = escena.cargar(self.user["id"])["version"]
        with self.assertRaises(tools.ToolExecutionFailed) as error:
            await self.run_tool("estudio.funcion", expresion="a*x")
        self.assertIn("estudio_parametro", str(error.exception))
        self.assertEqual(escena.cargar(self.user["id"])["version"], version)

    async def test_avisa_si_la_curva_se_sale(self):
        await self.run_tool("estudio.nueva_escena", titulo="Prueba", rango_y=[-1, 1])
        resultado = await self.run_tool("estudio.funcion", expresion="x^3")
        self.assertTrue(any("estudio_ejes" in aviso for aviso in resultado["avisos"]))

    async def test_un_paso_no_puede_nombrar_algo_que_no_existe(self):
        await self.run_tool("estudio.nueva_escena", titulo="Prueba")
        with self.assertRaises(tools.ToolExecutionFailed):
            await self.run_tool("estudio.paso", texto="Mira", mostrar=["fantasma"])

    async def test_quitar_limpia_los_pasos(self):
        await self.run_tool("estudio.nueva_escena", titulo="Prueba")
        await self.run_tool("estudio.funcion", expresion="x", id="recta")
        await self.run_tool("estudio.funcion", expresion="x^2", id="parabola")
        await self.run_tool("estudio.paso", texto="La parábola", mostrar=["parabola"])
        quitado = await self.run_tool("estudio.quitar", id="parabola")
        self.assertEqual(quitado["pasos_que_lo_nombraban"], [1])
        self.assertTrue((await self.run_tool("estudio.validar"))["ok"])

    async def test_no_se_quita_un_deslizador_en_uso(self):
        await self.run_tool("estudio.nueva_escena", titulo="Prueba")
        await self.run_tool("estudio.parametro", id="a", etiqueta="a", minimo=0, maximo=2, valor=1)
        await self.run_tool("estudio.funcion", expresion="a*x", id="recta")
        with self.assertRaises(tools.ToolExecutionFailed):
            await self.run_tool("estudio.quitar", id="a")

    async def test_simulacion_con_deslizador(self):
        await self.run_tool("estudio.nueva_escena", titulo="Péndulo")
        await self.run_tool("estudio.parametro", id="L", etiqueta="Longitud", minimo=0.5, maximo=5, valor=2)
        resultado = await self.run_tool(
            "estudio.simulacion", modelo="pendulo", parametros={"longitud": "L", "angulo_inicial": 10}
        )
        esperado = 2 * math.pi * math.sqrt(2 / 9.81)
        self.assertAlmostEqual(
            resultado["magnitudes_calculadas"]["periodo_pequenas_oscilaciones_s"], esperado, places=2
        )
        self.assertIn("nota", resultado)

    async def test_un_deslizador_no_puede_salirse_de_lo_fisico(self):
        await self.run_tool("estudio.nueva_escena", titulo="Péndulo")
        await self.run_tool("estudio.parametro", id="L", etiqueta="Longitud", minimo=0, maximo=5, valor=2)
        with self.assertRaises(tools.ToolExecutionFailed):
            await self.run_tool("estudio.simulacion", modelo="pendulo", parametros={"longitud": "L"})

    async def test_grafo_y_dijkstra(self):
        await self.run_tool("estudio.nueva_escena", titulo="Dijkstra")
        await self.run_tool(
            "estudio.grafo",
            id="mapa",
            nodos=Algoritmos.NODOS,
            aristas=Algoritmos.ARISTAS,
        )
        resultado = await self.run_tool(
            "estudio.recorrido", grafo="mapa", algoritmo="dijkstra", origen="A", destino="E"
        )
        self.assertEqual(resultado["resultado"]["coste"], 7)
        grafo = escena.cargar(self.user["id"])["elementos"][0]
        self.assertEqual(grafo["recorrido"]["algoritmo"], "dijkstra")
        # El algoritmo es del engine, pero el grafo lo dio el modelo.
        self.assertEqual(grafo["procedencia"]["origen"], "modelo")

    async def test_los_mensajes_usan_los_nombres_de_los_nodos(self):
        await self.run_tool("estudio.nueva_escena", titulo="Circulación")
        await self.run_tool(
            "estudio.grafo",
            id="sangre",
            dirigido=True,
            nodos=[{"id": "AD", "etiqueta": "Aurícula dcha."}, {"id": "VD", "etiqueta": "Ventrículo dcho."}],
            aristas=[{"desde": "AD", "hasta": "VD"}],
        )
        await self.run_tool("estudio.recorrido", grafo="sangre", algoritmo="bfs", origen="AD", destino="VD")
        fotogramas = escena.cargar(self.user["id"])["elementos"][0]["recorrido"]["fotogramas"]
        self.assertIn("Aurícula dcha.", fotogramas[0]["mensaje"])
        self.assertIn("Aurícula dcha. → Ventrículo dcho.", fotogramas[-1]["mensaje"])

    async def test_molecula_sin_red_usa_la_local(self):
        await self.run_tool("estudio.nueva_escena", titulo="Agua", modo="3d")
        with patch.object(
            moleculas, "desde_pubchem", AsyncMock(side_effect=primitivas.httpx.ConnectError("sin red"))
        ):
            resultado = await self.run_tool("estudio.molecula", nombre="agua")
        self.assertEqual(resultado["formula"], "H2O")

    async def test_sin_modelos_lo_dice(self):
        with patch.object(modelos, "INCLUIDOS", Path(self.tempdir.name) / "nada"):
            resultado = await self.run_tool("estudio.modelo")
        self.assertEqual(resultado["disponibles"], [])
        self.assertIn("No los inventes", resultado["nota"])

    async def test_el_corazon_viene_incluido_y_se_senala_por_partes(self):
        disponibles = (await self.run_tool("estudio.modelo"))["disponibles"]
        corazon = next(m for m in disponibles if m["id"] == "corazon")
        self.assertIn("Válvula aórtica", corazon["partes"])
        # Un nombre agrupa sus mallas, y no se repite en la lista.
        self.assertEqual(corazon["partes"].count("Válvula aórtica"), 1)

        await self.run_tool("estudio.nueva_escena", titulo="Corazón", modo="3d")
        cargado = await self.run_tool(
            "estudio.modelo", modelo="corazon", id="corazon", resaltar=["Válvula aórtica", "Bazo"]
        )
        self.assertEqual(cargado["resaltadas"], ["Válvula aórtica"])
        self.assertEqual(cargado["no_existen"], ["Bazo"])
        elemento = escena.cargar(self.user["id"])["elementos"][0]
        self.assertEqual(len(elemento["resaltadas"]), 3)  # las tres valvas
        self.assertEqual(elemento["procedencia"]["origen"], "catalogo")

        await self.run_tool("estudio.paso", texto="Aquí", resaltar=["corazon.Ventrículo izquierdo"])
        with self.assertRaises(tools.ToolExecutionFailed) as error:
            await self.run_tool("estudio.paso", texto="Aquí", resaltar=["corazon.Ventrículo central"])
        self.assertIn("Ventrículo izquierdo", str(error.exception))

    async def test_ir_a_paso_avisa_a_todas_las_ventanas(self):
        await self.run_tool("estudio.nueva_escena", titulo="Prueba")
        await self.run_tool("estudio.funcion", expresion="x", id="recta")
        await self.run_tool("estudio.paso", texto="Uno")
        await self.run_tool("estudio.paso", texto="Dos")
        await self.run_tool("estudio.ir_a_paso", numero=2)
        self.assertEqual(self.enviados[-1], {"tipo": "estudio_paso", "indice": 1})

    async def _con_pregunta(self):
        await self.run_tool("estudio.nueva_escena", titulo="Péndulo")
        await self.run_tool("estudio.funcion", expresion="x", id="recta")
        await self.run_tool("estudio.paso", texto="Mira la recta", idea="Una recta")
        await self.run_tool(
            "estudio.paso",
            texto="¿Qué pasa si duplicas la masa?",
            idea="La masa no cuenta",
            pregunta={
                "enunciado": "¿Cambia el periodo?",
                "opciones": ["Se duplica", "Se reduce a la mitad", "No cambia"],
                "correcta": 2,
                "explicacion": "El periodo solo depende de la longitud y de g",
                "pistas": ["Mueve la masa y mira el reloj"],
            },
        )

    async def test_cada_fallo_destapa_una_pista_y_luego_la_explicacion(self):
        await self._con_pregunta()
        primero = await escena.responder(self.user["id"], 1, 0)
        self.assertEqual(primero["pista"], "Mueve la masa y mira el reloj")
        self.assertFalse(primero["resuelta"])
        self.assertIsNone(primero["explicacion"])
        self.assertEqual(
            self.enviados[-1], {"tipo": "estudio_respuesta", "indice": 1, "elegidas": [0]}
        )
        with self.assertRaises(escena.EscenaError):
            await escena.responder(self.user["id"], 1, 0)
        segundo = await escena.responder(self.user["id"], 1, 1)
        self.assertTrue(segundo["resuelta"])
        self.assertFalse(segundo["acertada"])
        self.assertIn("longitud", segundo["explicacion"])
        with self.assertRaises(escena.EscenaError):
            await escena.responder(self.user["id"], 1, 2)

        vista = await self.run_tool("estudio.ver_escena")
        self.assertEqual(
            vista["pasos"][1]["alumno"],
            {
                "eligio": ["Se duplica", "Se reduce a la mitad"],
                "acerto": False,
                "a_la_primera": False,
                "resuelta": True,
            },
        )
        self.assertNotIn("alumno", vista["pasos"][0])

    async def test_sustituir_el_paso_olvida_lo_respondido(self):
        await self._con_pregunta()
        await escena.responder(self.user["id"], 1, 2)
        await self.run_tool("estudio.paso", numero=2, texto="Otra forma de verlo", idea="Igual")
        self.assertEqual(escena.cargar(self.user["id"])["progreso"]["respuestas"], {})

    async def test_recuerda_hasta_donde_ha_llegado(self):
        await self._con_pregunta()
        await escena.cambiar_paso(self.user["id"], 1)
        await escena.cambiar_paso(self.user["id"], 0)
        vista = await self.run_tool("estudio.ver_escena")
        self.assertEqual((vista["paso_actual"], vista["visto_hasta"]), (1, 2))

    async def test_la_nueva_escena_trae_como_dar_la_clase(self):
        respuesta = await self.run_tool("estudio.nueva_escena", titulo="Prueba")
        self.assertTrue(any("tutor" in regla for regla in respuesta["como_tutor"]))

    async def test_avisa_de_una_clase_que_no_pide_nada(self):
        await self.run_tool("estudio.nueva_escena", titulo="Prueba")
        await self.run_tool("estudio.funcion", expresion="x", id="recta")
        largo = await self.run_tool("estudio.paso", texto="bla " * 120)
        self.assertEqual(len(largo["avisos"]), 2)
        await self.run_tool("estudio.paso", texto="Dos", idea="Dos")
        await self.run_tool("estudio.paso", texto="Tres", idea="Tres")
        avisos = (await self.run_tool("estudio.validar"))["avisos"]
        self.assertTrue(any("Ningún paso le pide nada" in a for a in avisos))
        self.assertIn("Pasos sin «idea»: 1", avisos)
        self.assertIn("Pasos demasiado largos para una sola idea: 1", avisos)

    async def test_la_escena_sobrevive_a_un_reinicio(self):
        await self.run_tool("estudio.nueva_escena", titulo="Persistente")
        escena.olvidar_cache()
        self.assertEqual(escena.cargar(self.user["id"])["titulo"], "Persistente")

    async def test_captura_ida_y_vuelta(self):
        async def ventana():
            while not any(e.get("tipo") == "estudio_captura" for e in self.enviados):
                await asyncio.sleep(0.01)
            captura_id = next(
                e["captura_id"] for e in self.enviados if e.get("tipo") == "estudio_captura"
            )
            capturas.depositar(captura_id, self.user["id"], b"\xff\xd8jpeg")

        tarea = asyncio.create_task(ventana())
        resultado = await self.run_tool("estudio.captura")
        await tarea
        self.assertEqual(resultado["image"]["media_type"], "image/jpeg")

    async def test_captura_sin_ventanas_no_se_queda_colgada(self):
        with patch.object(capturas, "ESPERA", 0.05):
            async def recoger_rapido(captura_id, espera=0.05):
                return await RECOGER(captura_id, 0.05)

            with patch.object(capturas, "recoger", recoger_rapido):
                with self.assertRaises(tools.ToolError):
                    await self.run_tool("estudio.captura")


RECOGER = capturas.recoger


class Api(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        for parche in (
            patch.object(settings, "db_path", str(root / "vibi.db")),
            patch.object(settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"),
        ):
            parche.start()
            self.addCleanup(parche.stop)
        db.init_db()
        escena.olvidar_cache()
        self.addCleanup(escena.olvidar_cache)
        from app.main import create_app

        self.client = TestClient(create_app(start_background=False))
        self.user = db.get_or_create_user("ana")
        self.cabeceras = {"Authorization": f"Bearer {auth.create_access_token(self.user['id'])}"}

    def test_la_escena_requiere_sesion(self):
        self.assertEqual(self.client.get("/api/estudio/escena").status_code, 401)

    def test_devuelve_una_escena_vacia(self):
        respuesta = self.client.get("/api/estudio/escena", headers=self.cabeceras)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["elementos"], [])

    def test_paso_sin_pasos_es_un_400(self):
        respuesta = self.client.post(
            "/api/estudio/paso", json={"indice": 0}, headers=self.cabeceras
        )
        self.assertEqual(respuesta.status_code, 400)

    def test_responder_sin_pregunta_es_un_400(self):
        respuesta = self.client.post(
            "/api/estudio/respuesta", json={"indice": 0, "opcion": 0}, headers=self.cabeceras
        )
        self.assertEqual(respuesta.status_code, 400)

    def test_una_captura_que_no_se_espera_es_un_404(self):
        respuesta = self.client.post(
            "/api/estudio/capturas/nada", content=b"\xff\xd8x", headers=self.cabeceras
        )
        self.assertEqual(respuesta.status_code, 404)

    def test_un_modelo_inexistente_es_un_404(self):
        respuesta = self.client.get(
            "/api/estudio/modelos/unicornio/archivo", headers=self.cabeceras
        )
        self.assertEqual(respuesta.status_code, 404)

    def test_sirve_el_corazon_incluido_sin_rutas_del_servidor(self):
        lista = self.client.get("/api/estudio/modelos", headers=self.cabeceras).json()
        self.assertTrue(all("_carpeta" not in m for m in lista))
        respuesta = self.client.get("/api/estudio/modelos/corazon/archivo", headers=self.cabeceras)
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.content.startswith(b"glTF"))


class Composicion(_ConUsuario):
    """Las piezas generales: nada de casos programados."""

    async def test_un_pendulo_escrito_como_ecuaciones(self):
        await self.run_tool("estudio.nueva_escena", titulo="Péndulo a mano")
        await self.run_tool("estudio.parametro", id="L", etiqueta="L", minimo=0.5, maximo=3, valor=1)
        resumen = await self.run_tool(
            "estudio.sistema",
            id="pendulo",
            variables={"theta": 0.1, "omega": 0},
            ecuaciones={"theta": "omega", "omega": "-9.81/L*sin(theta)"},
        )
        self.assertTrue(resumen["estable"])
        self.assertAlmostEqual(resumen["periodo_de_theta_s"], 2 * math.pi * math.sqrt(1 / 9.81), places=2)

    async def test_lorenz_no_tiene_periodo_pero_es_estable(self):
        await self.run_tool("estudio.nueva_escena", titulo="Lorenz")
        resumen = await self.run_tool(
            "estudio.sistema",
            id="lorenz",
            variables={"x": 1, "y": 1, "z": 1},
            ecuaciones={"x": "10*(y - x)", "y": "x*(28 - z) - y", "z": "x*y - 8/3*z"},
        )
        self.assertTrue(resumen["estable"])
        self.assertNotIn("periodo_de_x_s", resumen)
        self.assertIn("irregular", resumen["x_oscila"])
        self.assertLess(resumen["rangos"]["z"][1], 60)

    async def test_depredador_presa_tiene_periodo(self):
        await self.run_tool("estudio.nueva_escena", titulo="Lotka-Volterra")
        resumen = await self.run_tool(
            "estudio.sistema", id="lv", variables={"c": 10, "z": 5},
            ecuaciones={"c": "1.1*c - 0.4*c*z", "z": "0.1*c*z - 0.4*z"},
        )
        self.assertIn("periodo_de_c_s", resumen)

    async def test_avisa_si_el_sistema_diverge(self):
        await self.run_tool("estudio.nueva_escena", titulo="Explota")
        resumen = await self.run_tool(
            "estudio.sistema", id="malo", variables={"u": 1}, ecuaciones={"u": "u^2"}
        )
        self.assertFalse(resumen["estable"])
        self.assertAlmostEqual(resumen["diverge_en_t"], 1.0, places=1)

    async def test_ecuaciones_y_variables_tienen_que_casar(self):
        await self.run_tool("estudio.nueva_escena", titulo="Mal")
        with self.assertRaises(tools.ToolExecutionFailed):
            await self.run_tool(
                "estudio.sistema", id="s", variables={"a": 1}, ecuaciones={"b": "a"}
            )

    async def test_un_sistema_solar_compuesto(self):
        await self.run_tool("estudio.nueva_escena", titulo="Sol, Tierra y Luna", espacio=[14, 6, 14])
        await self.run_tool("estudio.objeto", id="sol", forma="esfera", tamano=[1], brillo=1.5, color="amarillo")
        tierra = await self.run_tool(
            "estudio.objeto", id="tierra", forma="esfera", tamano=[0.35],
            posicion=["5*cos(t/2)", 0, "5*sin(t/2)"], estela=600, color="azul",
        )
        luna = await self.run_tool(
            "estudio.objeto", id="luna", forma="esfera", padre="tierra", tamano=[0.1],
            posicion=["0.9*cos(3*t)", 0, "0.9*sin(3*t)"], color="gris",
        )
        self.assertEqual(tierra["posicion_en_t0"], [5.0, 0.0, 0.0])
        self.assertTrue(tierra["se_mueve"])
        self.assertEqual(luna["avisos"], [])
        guardado = escena.cargar(self.user["id"])
        self.assertEqual(esc_elemento(guardado, "luna")["padre"], "tierra")
        self.assertEqual(esc_elemento(guardado, "sol")["procedencia"]["origen"], "modelo")

    async def test_los_objetos_se_mueven_con_un_sistema(self):
        await self.run_tool("estudio.nueva_escena", titulo="Péndulo compuesto")
        await self.run_tool(
            "estudio.sistema", id="dinamica",
            variables={"theta": 0.8, "omega": 0},
            ecuaciones={"theta": "omega", "omega": "-9.81*sin(theta)"},
        )
        bola = await self.run_tool(
            "estudio.objeto", id="bola", forma="esfera", tamano=[0.25],
            posicion=["2*sin(theta)", "2 - 2*cos(theta)", 0],
        )
        self.assertTrue(bola["se_mueve"])
        self.assertEqual(bola["depende_de"], ["theta"])
        # No se puede quitar el sistema mientras algo dependa de él.
        with self.assertRaises(tools.ToolExecutionFailed):
            await self.run_tool("estudio.quitar", id="dinamica")
        self.assertTrue((await self.run_tool("estudio.validar"))["ok"])

    async def test_errores_que_explican_que_cambiar(self):
        await self.run_tool("estudio.nueva_escena", titulo="Errores")
        await self.run_tool("estudio.objeto", id="a", forma="grupo")
        await self.run_tool("estudio.objeto", id="b", forma="caja", padre="a")
        with self.assertRaises(tools.ToolExecutionFailed) as error:
            await self.run_tool("estudio.objeto", id="a", forma="grupo", padre="b")
        self.assertIn("ciclo", str(error.exception))
        with self.assertRaises(tools.ToolExecutionFailed) as error:
            await self.run_tool("estudio.objeto", id="c", forma="caja", tamano=[1])
        self.assertIn("ancho, alto, fondo", str(error.exception))
        lejos = await self.run_tool("estudio.objeto", id="d", forma="esfera", posicion=[40, 0, 0])
        self.assertTrue(lejos["avisos"])


def esc_elemento(guardada, elemento_id):
    return next(e for e in guardada["elementos"] if e["id"] == elemento_id)


class Atlas(_ConUsuario):
    """El atlas entero: buscar en el índice y cargar sin casos preparados."""

    async def test_busca_piezas_y_grupos(self):
        resultado = await self.run_tool("estudio.atlas_buscar", consulta="kidney")
        nombres = [p["nombre"] for p in resultado["piezas"]]
        self.assertEqual(nombres[:2], ["Kidney.l", "Kidney.r"])
        grupos = (await self.run_tool("estudio.atlas_buscar", consulta="urinary"))["grupos"]
        self.assertIn("Urinary system", [g["nombre"] for g in grupos])

    def test_un_grupo_se_expande_en_sus_piezas(self):
        piezas, desconocidas = atlas.expandir(["Urinary system", "Femur.l", "Riñón"])
        self.assertIn("Kidney.r", piezas)
        self.assertIn("Femur.l", piezas)
        self.assertEqual(desconocidas, ["Riñón"])

    async def test_sin_blender_lo_dice_y_no_inventa(self):
        await self.run_tool("estudio.nueva_escena", titulo="Riñón", modo="3d")
        with patch.object(settings, "estudio_atlas_blend", ""):
            with self.assertRaises(tools.ToolExecutionFailed) as error:
                await self.run_tool("estudio.atlas", estructuras=["Kidney.l"])
        self.assertIn("no inventes", str(error.exception))

    async def test_carga_con_nombres_y_rechaza_lo_que_no_existe(self):
        await self.run_tool("estudio.nueva_escena", titulo="Riñón", modo="3d")
        with patch.object(atlas, "exportar", AsyncMock(return_value="a" * 20)):
            cargado = await self.run_tool(
                "estudio.atlas", id="rinon", estructuras=["Urinary system"],
                nombres={"Kidney.l": "Riñón", "Kidney.r": "Riñón"}, resaltar=["Riñón"],
            )
            with self.assertRaises(tools.ToolExecutionFailed) as error:
                await self.run_tool("estudio.atlas", estructuras=["Kidney.x"])
        self.assertEqual(cargado["resaltadas"], ["Riñón"])
        self.assertIn("Riñón", cargado["nombres_para_senalar"])
        self.assertIn("Kidney.l", str(error.exception))  # sugiere las parecidas
        elemento = escena.cargar(self.user["id"])["elementos"][0]
        self.assertEqual(elemento["url"], f"/api/estudio/atlas/{'a' * 20}/archivo")
        self.assertEqual(elemento["procedencia"]["origen"], "catalogo")
        self.assertEqual(sorted(elemento["resaltadas"]), ["Kidney.l", "Kidney.r"])


def _glb_de_prueba(con_textura: bool = True) -> bytes:
    """Un coche mínimo como los de Kenney: carrocería y una rueda con nombre,
    y la textura fuera del .glb."""
    import struct as _struct

    posiciones = _struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": [
            {"name": "body", "mesh": 0, "translation": [0, 0.5, 0], "scale": [2, 1, 4]},
            {"name": "wheel-front-left", "mesh": 0, "translation": [1, 0, 1]},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
             "min": [0, 0, 0], "max": [1, 1, 0]}
        ],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(posiciones)}],
        "buffers": [{"byteLength": len(posiciones)}],
    }
    if con_textura:
        gltf["images"] = [{"uri": "Textures/colormap.png"}]
    return biblioteca._escribir_glb(gltf, posiciones)


UID_PRUEBA = "0123456789abcdef0123456789abcdef"


def _sketchfab_simulado(licencia="cc0", glb=None, estado_descarga=200):
    """Un Sketchfab de mentira: búsqueda, ficha, enlace de descarga y el .glb."""
    import httpx

    def resultado(uid, nombre, etiqueta, caras=5000, megas=2, descargable=True):
        return {
            "uid": uid, "name": nombre, "license": {"label": etiqueta},
            "isDownloadable": descargable, "faceCount": caras, "animationCount": 0,
            "user": {"displayName": "Ana Modela"},
            "archives": {"glb": {"size": megas * 1_000_000}},
        }

    def responder(peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        if ruta == "/v3/search":
            if peticion.url.params["license"] == "cc0":
                return httpx.Response(200, json={"results": [
                    resultado(UID_PRUEBA, "Microscope", "CC0 Public Domain"),
                    resultado("f" * 32, "Pesado", "CC0 Public Domain", megas=300),
                    resultado("e" * 32, "Enorme", "CC0 Public Domain", caras=2_000_000),
                ]})
            return httpx.Response(200, json={"results": [
                resultado("d" * 32, "Lab microscope", "CC Attribution"),
                resultado("c" * 32, "No comercial", "CC Attribution-NonCommercial"),
            ]})
        if ruta == f"/v3/models/{UID_PRUEBA}":
            return httpx.Response(200, json={
                "name": "Microscope", "license": {"slug": licencia},
                "user": {"displayName": "Ana Modela"},
                "viewerUrl": "https://sketchfab.com/3d-models/microscope",
            })
        if ruta == f"/v3/models/{UID_PRUEBA}/download":
            assert peticion.headers["Authorization"] == "Token secreto"
            return httpx.Response(estado_descarga, json={"glb": {"url": "https://cdn.prueba/m.glb", "size": 100}})
        if peticion.url.host == "cdn.prueba":
            return httpx.Response(200, content=glb or _glb_de_prueba(con_textura=False))
        return httpx.Response(404)

    real = httpx.AsyncClient

    def fabrica(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(responder), **kwargs)

    return patch.object(sketchfab.httpx, "AsyncClient", fabrica)


class Sketchfab(_ConUsuario):
    """Modelos realistas de fuera, solo con licencias que se pueden citar."""

    def setUp(self):
        super().setUp()
        biblioteca.olvidar_externos()
        self.addCleanup(biblioteca.olvidar_externos)
        token = patch.object(settings, "sketchfab_token", "secreto")
        token.start()
        self.addCleanup(token.stop)

    async def test_busca_filtrando_licencia_peso_y_caras(self):
        with _sketchfab_simulado():
            encontrados = await sketchfab.buscar("microscopio")
        self.assertEqual([e["titulo"] for e in encontrados], ["Microscope", "Lab microscope"])
        self.assertEqual(encontrados[0]["licencia"], "CC0")
        self.assertEqual(encontrados[1]["licencia"], "CC BY 4.0")

    async def test_importa_y_se_usa_como_uno_de_la_biblioteca(self):
        await self.run_tool("estudio.nueva_escena", titulo="Laboratorio")
        with _sketchfab_simulado():
            busqueda = await self.run_tool("estudio.biblioteca", consulta="microscope")
            self.assertEqual(busqueda["sketchfab"][0]["id"], f"sketchfab/{UID_PRUEBA}")
            creado = await self.run_tool(
                "estudio.objeto", id="micro", forma="modelo", modelo=f"sketchfab/{UID_PRUEBA}", tamano=[2],
            )
        self.assertIn("Ana Modela", creado["cita"])
        self.assertIn("frente", creado["colocacion"])
        self.assertEqual(creado["partes"], ["body", "wheel-front-left"])
        elemento = esc_elemento(escena.cargar(self.user["id"]), "micro")
        self.assertEqual(elemento["procedencia"]["url"], "https://sketchfab.com/3d-models/microscope")
        self.assertIn("CC0", elemento["procedencia"]["detalle"])
        self.assertTrue(biblioteca.ruta(f"sketchfab/{UID_PRUEBA}").is_file())
        # La segunda vez no hay red: está guardado, también tras reiniciar.
        biblioteca.olvidar_externos()
        await self.run_tool("estudio.objeto", id="otro", forma="modelo", modelo=f"sketchfab/{UID_PRUEBA}")

    async def test_rechaza_licencias_no_permitidas_y_tokens_malos(self):
        with _sketchfab_simulado(licencia="by-nc"):
            with self.assertRaises(biblioteca.BibliotecaError) as error:
                await sketchfab.importar(UID_PRUEBA)
        self.assertIn("licencia", str(error.exception))
        with _sketchfab_simulado(estado_descarga=401):
            with self.assertRaises(biblioteca.BibliotecaError) as error:
                await sketchfab.importar(UID_PRUEBA)
        self.assertIn("token", str(error.exception))
        with patch.object(settings, "sketchfab_token", ""):
            with self.assertRaises(biblioteca.BibliotecaError) as error:
                await sketchfab.importar(UID_PRUEBA)
        self.assertIn("SKETCHFAB_TOKEN", str(error.exception))
        with self.assertRaises(biblioteca.BibliotecaError):
            await sketchfab.importar("../../etc")

    async def test_no_acepta_lo_que_el_visor_no_abre(self):
        gltf, binario = biblioteca._leer_glb(_glb_de_prueba(con_textura=False))
        gltf["extensionsRequired"] = ["KHR_draco_mesh_compression"]
        with _sketchfab_simulado(glb=biblioteca._escribir_glb(gltf, binario)):
            with self.assertRaises(biblioteca.BibliotecaError) as error:
                await sketchfab.importar(UID_PRUEBA)
        self.assertIn("compresión", str(error.exception))

    async def test_si_el_cortafuegos_desafia_repite_con_curl(self):
        import httpx

        reto = httpx.MockTransport(
            lambda _: httpx.Response(202, headers={"x-amzn-waf-action": "challenge"})
        )
        curl = AsyncMock(return_value=sketchfab._Respuesta(200, b'{"ok": 1}'))
        with patch.object(sketchfab, "_con_curl", curl):
            async with httpx.AsyncClient(transport=reto) as cliente:
                respuesta = await sketchfab._pedir(
                    cliente, "https://api.sketchfab.com/v3/search", params={"q": "car"},
                    headers={"Authorization": "Token x"},
                )
        self.assertEqual(respuesta.json(), {"ok": 1})
        url, cabeceras = curl.await_args.args[:2]
        self.assertIn("q=car", url)
        self.assertEqual(cabeceras, {"Authorization": "Token x"})

    def test_las_partes_automaticas_no_cuentan(self):
        gltf, binario = biblioteca._leer_glb(_glb_de_prueba(con_textura=False))
        gltf["nodes"][0]["name"] = "Object_4"
        gltf["nodes"].append({"name": "Sketchfab_model", "children": [0, 1]})
        glb = biblioteca._escribir_glb(gltf, binario)
        self.assertEqual(
            sketchfab._partes_con_nombre(glb, ["Object_4", "wheel-front-left", "Sketchfab_model"]),
            ["wheel-front-left"],
        )


def _caja_obj(minimo, maximo, material="madera") -> str:
    """Una caja en .obj (12 triángulos), sin normales, con un material."""
    (x0, y0, z0), (x1, y1, z1) = minimo, maximo
    vertices = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    caras = ["1 2 4 3", "5 7 8 6", "1 5 6 2", "3 4 8 7", "1 3 7 5", "2 6 8 4"]
    return (
        "mtllib caja.mtl\n" + "".join(f"v {x} {y} {z}\n" for x, y, z in vertices)
        + f"usemtl {material}\n" + "".join(f"f {c}\n" for c in caras)
    )


def _armario_urdf(carpeta: Path) -> None:
    """Un armario de PartNet de juguete: puerta con bisagra en z y cajón en x."""
    (carpeta / "textured_objs").mkdir(parents=True)
    (carpeta / "textured_objs" / "caja.mtl").write_text("newmtl madera\nKd 0.6 0.4 0.2\n")
    (carpeta / "textured_objs" / "cuerpo.obj").write_text(_caja_obj((-0.5, 0, -0.3), (0.5, 1, 0.3)))
    # La puerta, en coordenadas del armario: de x = 0.5 a -0.5, delante (z = 0.3).
    (carpeta / "textured_objs" / "puerta.obj").write_text(_caja_obj((-0.5, 0, 0.3), (0.5, 1, 0.32)))
    (carpeta / "textured_objs" / "cajon.obj").write_text(_caja_obj((-0.4, 0.1, -0.2), (0.4, 0.3, 0.2)))
    (carpeta / "mobility.urdf").write_text("""<?xml version="1.0"?>
<robot name="armario">
  <link name="base"/>
  <link name="link_0"><visual><geometry><mesh filename="textured_objs/cuerpo.obj"/></geometry></visual></link>
  <link name="link_1"><visual><origin xyz="-0.5 0 -0.3"/><geometry><mesh filename="textured_objs/puerta.obj"/></geometry></visual></link>
  <link name="link_2"><visual><geometry><mesh filename="textured_objs/cajon.obj"/></geometry></visual></link>
  <joint name="j0" type="fixed"><parent link="base"/><child link="link_0"/></joint>
  <joint name="j1" type="revolute"><origin xyz="0.5 0 0.3"/><axis xyz="0 1 0"/>
    <parent link="link_0"/><child link="link_1"/><limit lower="-1.5708" upper="0"/></joint>
  <joint name="j2" type="prismatic"><origin xyz="0 0 0"/><axis xyz="0 0 1"/>
    <parent link="link_0"/><child link="link_2"/><limit lower="0" upper="0.4"/></joint>
</robot>""")
    (carpeta / "semantics.txt").write_text("link_0 static frame\nlink_1 hinge door\nlink_2 slider drawer\n")
    (carpeta / "meta.json").write_text('{"model_cat": "StorageFurniture"}')


class URDF(_ConUsuario):
    """Objetos de PartNet-Mobility: articulados de serie."""

    def setUp(self):
        super().setUp()
        biblioteca.olvidar_externos()
        self.addCleanup(biblioteca.olvidar_externos)
        self.carpeta = Path(self.tempdir.name) / "45001"
        _armario_urdf(self.carpeta)

    def test_cada_articulacion_es_un_nodo_con_el_eje_en_su_y(self):
        glb, articulaciones, titulo = urdf.convertir(self.carpeta)
        self.assertEqual(titulo, "StorageFurniture (door, drawer)")
        self.assertEqual(
            [(a["partes"], a["tipo"], a["eje"]) for a in articulaciones],
            [(["door"], "giro", "y"), (["drawer"], "desliza", "y")],
        )
        self.assertEqual((articulaciones[0]["minimo"], articulaciones[0]["maximo"]), (-90.0, 0.0))
        self.assertEqual(articulaciones[1]["maximo"], 0.4)
        gltf, _ = biblioteca._leer_glb(glb)
        nodos = {n.get("name"): n for n in gltf["nodes"]}
        # El cajón se desliza en z: su nodo lleva el y local hasta z.
        cajon = biblioteca._matriz(nodos["drawer"])
        self.assertAlmostEqual(cajon[4 + 2], 1.0, places=5)  # columna y → (0, 0, 1)
        # La bisagra de la puerta está en (0.5, 0, 0.3) y gira en y del archivo.
        self.assertEqual(nodos["door"]["translation"], [0.5, 0.0, 0.3])
        ficha = biblioteca.describir("partnet", "45001", glb)
        self.assertEqual(ficha["medidas"], [1.0, 1.0, 0.62])
        self.assertEqual(sorted(ficha["partes"]), ["door", "drawer", "frame"])

    async def test_se_importa_y_sale_articulado_en_la_escena(self):
        ficha = urdf.importar(self.carpeta)
        self.assertEqual(ficha["id"], "partnet/45001")
        encontrados = [m["id"] for m in biblioteca.buscar("furniture")["modelos"]]
        self.assertIn("partnet/45001", encontrados)
        await self.run_tool("estudio.nueva_escena", titulo="Armario")
        creado = await self.run_tool("estudio.objeto", id="armario", forma="modelo", modelo="partnet/45001", tamano=[2])
        self.assertEqual(len(creado["articulaciones"]), 2)
        elemento = esc_elemento(escena.cargar(self.user["id"]), "armario")
        cajon = elemento["articulaciones"][1]
        # 0.4 unidades del archivo, con el armario escalado ×2: 0.8 en la escena.
        self.assertEqual((cajon["tipo"], cajon["maximo"]), ("desliza", 0.8))
        self.assertIn("PartNet-Mobility", elemento["procedencia"]["detalle"])

    def test_no_sale_de_su_carpeta_ni_lee_lo_que_no_sabe(self):
        urdf_texto = (self.carpeta / "mobility.urdf").read_text()
        (self.carpeta / "mobility.urdf").write_text(urdf_texto.replace("textured_objs/cajon.obj", "../../secreto.obj"))
        with self.assertRaises(urdf.URDFError) as error:
            urdf.convertir(self.carpeta)
        self.assertIn("fuera", str(error.exception))
        (self.carpeta / "mobility.urdf").write_text(urdf_texto.replace("cajon.obj", "cajon.stl"))
        with self.assertRaises(urdf.URDFError):
            urdf.convertir(self.carpeta)

    def test_lee_obj_con_poligonos_uv_normales_e_indices_negativos(self):
        obj = Path(self.tempdir.name) / "quad.obj"
        obj.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
                       "vn 0 0 1\nf -4/-4/1 -3/-3/1 -2/-2/1 -1/-1/1\n")
        malla, = urdf.leer_obj(obj)
        self.assertEqual(malla["indices"], [0, 1, 2, 0, 2, 3])
        self.assertEqual(malla["uvs"][2], (1.0, 1.0))
        self.assertEqual(malla["normales"][0], (0.0, 0.0, 1.0))


def _fal_simulado(pasos_en_cola=1, pedidos=None):
    """Un fal.ai de mentira: cola, estado, resultado y el .glb generado."""
    import httpx

    pedidos = pedidos if pedidos is not None else []
    estado = {"consultas": 0}

    def responder(peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        if peticion.method == "POST":
            assert peticion.headers["Authorization"] == "Key clave"
            pedidos.append(json.loads(peticion.content))
            return httpx.Response(200, json={
                "request_id": "r1",
                "status_url": "https://queue.fal.run/x/requests/r1/status",
                "response_url": "https://queue.fal.run/x/requests/r1",
            })
        if ruta.endswith("/status"):
            estado["consultas"] += 1
            hecho = estado["consultas"] > pasos_en_cola
            return httpx.Response(200, json={"status": "COMPLETED" if hecho else "IN_PROGRESS"})
        if ruta.endswith("/requests/r1"):
            return httpx.Response(200, json={"model_glb": {"url": "https://cdn.fal/m.glb", "file_size": 10}})
        if peticion.url.host == "cdn.fal":
            return httpx.Response(200, content=_glb_de_prueba(con_textura=False))
        return httpx.Response(404)

    real = httpx.AsyncClient

    def fabrica(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(responder), **kwargs)

    return patch.object(generacion.httpx, "AsyncClient", fabrica)


class Generacion(_ConUsuario):
    """Lo que no está en ninguna biblioteca, generado con IA y marcado como tal."""

    def setUp(self):
        super().setUp()
        biblioteca.olvidar_externos()
        self.addCleanup(biblioteca.olvidar_externos)
        generacion._tareas.clear()
        generacion._cuentas.clear()
        for parche in (
            patch.object(settings, "fal_key", "clave"),
            patch.object(generacion, "INTERVALO", 0.01),
        ):
            parche.start()
            self.addCleanup(parche.stop)

    async def test_genera_una_vez_y_va_como_redactado(self):
        await self.run_tool("estudio.nueva_escena", titulo="Motor")
        pedidos = []
        with _fal_simulado(pedidos=pedidos):
            listo = await composicion._generar_modelo(self.user, composicion.GenerarModeloArgs(
                descripcion="A four-stroke engine, metal", id="motor", tamano=3, etiqueta="Motor",
            ))
        self.assertEqual(listo["estado"], "listo")
        self.assertEqual(pedidos[0]["prompt"], "A four-stroke engine, metal")
        self.assertGreaterEqual(pedidos[0]["face_count"], 40_000)
        elemento = esc_elemento(escena.cargar(self.user["id"]), "motor")
        self.assertEqual(elemento["procedencia"]["origen"], "modelo")
        self.assertIn("Generado por IA", elemento["procedencia"]["detalle"])
        self.assertEqual(elemento["partes"], {})
        # La misma descripción (con otras mayúsculas) no se vuelve a generar.
        with _fal_simulado(pedidos=pedidos):
            await composicion._generar_modelo(self.user, composicion.GenerarModeloArgs(
                descripcion="a four-stroke   ENGINE, metal", id="motor2",
            ))
        self.assertEqual(len(pedidos), 1)
        self.assertTrue(biblioteca.publico(biblioteca.ficha(generacion.id_de("A four-stroke engine, metal")))["generado"])

    async def test_si_tarda_sigue_sola_y_luego_se_recoge(self):
        await self.run_tool("estudio.nueva_escena", titulo="Lento")
        with _fal_simulado(pasos_en_cola=30):
            with self.assertRaises(generacion.GeneracionPendiente):
                await generacion.obtener(self.user["id"], "a slow volcano", espera=0.05)
            ficha = await generacion.obtener(self.user["id"], "a slow volcano", espera=5)
        self.assertEqual(ficha["titulo"], "a slow volcano")
        self.assertEqual(generacion._cuentas[(self.user["id"], time.strftime("%Y-%m-%d"))], 1)

    async def test_tope_diario_y_sin_clave(self):
        with patch.object(settings, "estudio_generaciones_por_dia", 1), _fal_simulado():
            await generacion.obtener(self.user["id"], "a red apple")
            with self.assertRaises(biblioteca.BibliotecaError) as error:
                await generacion.obtener(self.user["id"], "a green apple")
        self.assertIn("tope", str(error.exception))
        generacion._cuentas.clear()
        with patch.object(settings, "fal_key", ""):
            with self.assertRaises(biblioteca.BibliotecaError) as error:
                await generacion.obtener(self.user["id"], "a blue apple")
        self.assertIn("FAL_KEY", str(error.exception))


class Biblioteca(_ConUsuario):
    """Objetos reales de Kenney en vez de coches hechos con cajas."""

    def test_busca_en_ingles_y_en_espanol_sin_falsos_amigos(self):
        coche = [m["id"] for m in biblioteca.buscar("coche")["modelos"]]
        self.assertEqual(coche[0], "car-kit/sedan")
        car = [m["id"] for m in biblioteca.buscar("car")["modelos"]]
        self.assertNotIn("food-kit/carrot", car)  # «car» no es «carrot»
        ruedas = [m["id"] for m in biblioteca.buscar("wheels")["modelos"]]
        self.assertTrue(all(i.startswith("car-kit/wheel") for i in ruedas[:4]))

    def test_las_ruedas_del_indice_son_partes(self):
        sedan = biblioteca.ficha("car-kit/sedan")
        partes, sueltas = biblioteca.expandir_partes(sedan, ["wheel*", "motor"])
        self.assertEqual(len(partes), 4)
        self.assertEqual(sueltas, ["motor"])

    def test_mete_la_textura_dentro_y_mide_con_las_transformaciones(self):
        textura = b"\x89PNG-de-mentira"
        glb = biblioteca.empaquetar(
            _glb_de_prueba(), lambda uri: textura if uri == "Textures/colormap.png" else None
        )
        gltf, binario = biblioteca._leer_glb(glb)
        imagen = gltf["images"][0]
        self.assertNotIn("uri", imagen)
        vista = gltf["bufferViews"][imagen["bufferView"]]
        self.assertEqual(binario[vista["byteOffset"] : vista["byteOffset"] + vista["byteLength"]], textura)
        # El trozo binario lleva hasta 3 bytes de relleno, como manda glTF.
        self.assertIn(len(binario) - gltf["buffers"][0]["byteLength"], range(4))
        ficha = biblioteca.describir("car-kit", "prueba", glb)
        # Carrocería escalada 2×1 desde (0, 0.5) y rueda desde (1, 0, 1):
        # x 0–2, y 0–1.5, z 0–1.
        self.assertEqual(ficha["medidas"], [2.0, 1.5, 1.0])
        self.assertEqual(ficha["partes"], ["body", "wheel-front-left"])

    def test_instala_un_kit_desde_su_zip(self):
        import io as _io
        import zipfile as _zipfile

        memoria = _io.BytesIO()
        with _zipfile.ZipFile(memoria, "w") as zip_:
            zip_.writestr("Models/GLB format/prueba.glb", _glb_de_prueba())
            zip_.writestr("Models/GLB format/Textures/colormap.png", b"png")
            zip_.writestr("Models/OBJ format/prueba.obj", "o nada")
        fichas = biblioteca.instalar("car-kit", memoria.getvalue())
        self.assertEqual([f["id"] for f in fichas], ["car-kit/prueba"])
        instalado = biblioteca.carpeta() / "car-kit" / "prueba.glb"
        gltf, _ = biblioteca._leer_glb(instalado.read_bytes())
        self.assertIn("bufferView", gltf["images"][0])

    async def test_un_coche_de_verdad_con_ruedas_que_giran(self):
        await self.run_tool("estudio.nueva_escena", titulo="F = m·a")
        await self.run_tool("estudio.parametro", id="v", etiqueta="Velocidad", minimo=0, maximo=3, valor=1)
        with patch.object(biblioteca, "asegurar", AsyncMock()):
            coche = await self.run_tool(
                "estudio.objeto", id="coche", forma="modelo", modelo="car-kit/sedan",
                tamano=[3], posicion=["v*t", -1, 0], rotacion=[0, 90, 0],
                girar_partes=[{"partes": ["wheel*"], "angulo": "v*t*180/pi/0.3"}],
            )
            with self.assertRaises(tools.ToolExecutionFailed) as error:
                await self.run_tool(
                    "estudio.objeto", id="otro", forma="modelo", modelo="car-kit/sedan",
                    girar_partes=[{"partes": ["helice"], "angulo": 10}],
                )
            self.assertIn("wheel-front-left", str(error.exception))
            with self.assertRaises(tools.ToolExecutionFailed) as error:
                await self.run_tool("estudio.objeto", id="otro", forma="modelo", modelo="car-kit/nave")
            self.assertIn("estudio_biblioteca", str(error.exception))
        self.assertEqual(coche["medidas_en_escena"]["largo_z"], 3)
        self.assertTrue(coche["se_mueve"])
        self.assertIn("wheel-back-left", coche["partes"])
        elemento = esc_elemento(escena.cargar(self.user["id"]), "coche")
        self.assertEqual(elemento["url"], "/api/estudio/biblioteca/car-kit/sedan")
        ruedas = elemento["articulaciones"][0]
        self.assertEqual((len(ruedas["partes"]), ruedas["tipo"], ruedas["eje"]), (4, "giro", "x"))
        self.assertEqual(elemento["procedencia"]["origen"], "catalogo")
        self.assertEqual(elemento["usa"], ["v"])
        # Las partes se señalan en los pasos como las de un modelo del catálogo.
        await self.run_tool("estudio.paso", texto="Las ruedas", resaltar=["coche.wheel-front-left"])
        with self.assertRaises(tools.ToolExecutionFailed):
            await self.run_tool("estudio.paso", texto="?", resaltar=["coche.volante"])

    async def test_colorear_ocultar_y_retocar_sin_rehacer(self):
        await self.run_tool("estudio.nueva_escena", titulo="Taller")
        with patch.object(biblioteca, "asegurar", AsyncMock()):
            await self.run_tool(
                "estudio.objeto", id="coche", forma="modelo", modelo="car-kit/sedan",
                tamano=[3], colores_partes={"body": "rojo"}, ocultar_partes=["wheel-front*"],
                etiqueta="Sedán",
            )
            elemento = esc_elemento(escena.cargar(self.user["id"]), "coche")
            self.assertEqual(elemento["ajustes"]["body"]["color"], "#ef4444")
            self.assertTrue(elemento["ajustes"]["wheel-front-left"]["oculta"])
            with self.assertRaises(tools.ToolExecutionFailed) as error:
                await self.run_tool(
                    "estudio.objeto", id="mal", forma="modelo", modelo="car-kit/sedan",
                    colores_partes={"capo": "azul"},
                )
            self.assertIn("colores_partes", str(error.exception))
            with self.assertRaises(tools.ToolExecutionFailed):
                await self.run_tool("estudio.objeto", id="caja", forma="caja", ocultar_partes=["x"])
            # Retocar cambia solo lo pedido: la etiqueta y los colores siguen.
            await self.run_tool("estudio.editar_objeto", id="coche", posicion=[1, 0, 0])
        elemento = esc_elemento(escena.cargar(self.user["id"]), "coche")
        self.assertEqual(elemento["posicion"], ["1.0", "0.0", "0.0"])
        self.assertEqual(elemento["etiqueta"], "Sedán")
        self.assertEqual(elemento["ajustes"]["body"]["color"], "#ef4444")
        with self.assertRaises(tools.ToolExecutionFailed) as error:
            await self.run_tool("estudio.editar_objeto", id="nada", posicion=[0, 0, 0])
        self.assertIn("estudio_objeto", str(error.exception))

    async def test_el_alumno_mueve_objetos_y_partes_a_mano(self):
        await self.run_tool("estudio.nueva_escena", titulo="A mano")
        await self.run_tool("estudio.objeto", id="bola", forma="esfera", posicion=[0, 1, 0])
        await self.run_tool("estudio.objeto", id="luna", forma="esfera", posicion=["cos(t)", 0, 0])
        with patch.object(biblioteca, "asegurar", AsyncMock()):
            await self.run_tool("estudio.objeto", id="coche", forma="modelo", modelo="car-kit/sedan")
        usuario = self.user["id"]
        movida = await composicion.ajustar_a_mano(
            usuario, "bola", posicion=[2.5, 1, -0.123456], rotacion=[0, 90, 0]
        )
        self.assertEqual(movida["posicion"], ["2.5", "1", "-0.1235"])
        self.assertTrue(movida["manual"])
        self.assertEqual(movida["original"]["posicion"], ["0.0", "1.0", "0.0"])
        # Lo animado no se toca a mano: el gizmo pisaría la fórmula.
        with self.assertRaises(escena.EscenaError) as error:
            await composicion.ajustar_a_mano(usuario, "luna", posicion=[1, 1, 1])
        self.assertIn("fórmulas", str(error.exception))
        restablecida = await composicion.ajustar_a_mano(usuario, "bola", restablecer=True)
        self.assertEqual(restablecida["posicion"], ["0.0", "1.0", "0.0"])
        self.assertFalse(restablecida["manual"])
        # Una parte guarda su transformación local, y sobrevive a que el modelo rehaga el coche.
        await composicion.ajustar_a_mano(
            usuario, "coche", parte="wheel-front-left", posicion=[0.5, 0.2, 1], rotacion=[0, 0, 30]
        )
        with self.assertRaises(escena.EscenaError):
            await composicion.ajustar_a_mano(usuario, "coche", parte="volante", posicion=[0, 0, 0])
        with patch.object(biblioteca, "asegurar", AsyncMock()):
            await self.run_tool("estudio.objeto", id="coche", forma="modelo", modelo="car-kit/sedan", tamano=[4])
        coche = esc_elemento(escena.cargar(usuario), "coche")
        self.assertEqual(coche["ajustes"]["wheel-front-left"]["rotacion"], [0.0, 0.0, 30.0])
        resumen = await self.run_tool("estudio.ver_escena")
        self.assertIn("manual", next(e for e in resumen["elementos"] if e["id"] == "coche"))
        self.assertNotIn("manual", next(e for e in resumen["elementos"] if e["id"] == "bola"))
        await composicion.ajustar_a_mano(usuario, "coche", parte="wheel-front-left", restablecer=True)
        self.assertNotIn("wheel-front-left", esc_elemento(escena.cargar(usuario), "coche").get("ajustes", {}))

    async def test_puertas_y_cajones_con_topes(self):
        nevera = biblioteca.publico(biblioteca.ficha("furniture-kit/kitchenFridge"))
        self.assertIn("bisagra", nevera["articulables"]["doorFridge"])
        await self.run_tool("estudio.nueva_escena", titulo="La nevera")
        await self.run_tool("estudio.parametro", id="abre", etiqueta="Apertura", minimo=0, maximo=1, valor=0.5)
        with patch.object(biblioteca, "asegurar", AsyncMock()):
            creada = await self.run_tool(
                "estudio.objeto", id="nevera", forma="modelo", modelo="furniture-kit/kitchenFridge",
                articulaciones=[
                    {"partes": ["doorFridge"], "eje": "y", "valor": "-100*abre", "minimo": -100,
                     "maximo": 0, "etiqueta": "Puerta"},
                ],
                girar_partes=[{"partes": ["doorFreezer"], "eje": "y", "angulo": 0}],
            )
            self.assertEqual(creada["articulaciones"][1]["etiqueta"], "Puerta")
            with self.assertRaises(tools.ToolExecutionFailed) as error:
                await self.run_tool(
                    "estudio.objeto", id="mal", forma="modelo", modelo="furniture-kit/kitchenFridge",
                    articulaciones=[{"partes": ["doorFridge"], "minimo": 10, "maximo": 0}],
                )
            self.assertIn("minimo", str(error.exception))
            with self.assertRaises(tools.ToolExecutionFailed):
                await self.run_tool(
                    "estudio.objeto", id="mal", forma="modelo", modelo="furniture-kit/kitchenFridge",
                    articulaciones=[{"partes": ["bisagra"]}],
                )
            # Retocar conserva las articulaciones.
            await self.run_tool("estudio.editar_objeto", id="nevera", color="blanco")
        elemento = esc_elemento(escena.cargar(self.user["id"]), "nevera")
        puerta = elemento["articulaciones"][1]
        self.assertEqual(
            (puerta["partes"], puerta["valor"], puerta["minimo"], puerta["maximo"]),
            (["doorFridge"], "-100 * abre", -100, 0),
        )
        self.assertEqual(elemento["usa"], ["abre"])

    async def test_sin_red_lo_dice(self):
        await self.run_tool("estudio.nueva_escena", titulo="Sin red")
        with patch.object(biblioteca, "_descargar", AsyncMock(side_effect=biblioteca.BibliotecaError("sin red"))):
            with self.assertRaises(tools.ToolExecutionFailed) as error:
                await self.run_tool("estudio.objeto", id="c", forma="modelo", modelo="car-kit/van")
        self.assertIn("sin red", str(error.exception))


class ReglasDeTurno(TestCase):
    """Un modelo pequeño no relaciona el prefijo con la descripción de una herramienta."""

    def test_claude_las_recibe_solo_desde_estudio(self):
        from app.executors import claude_chat

        desde_estudio = claude_chat._prompt_with_attachments("(Estudio, paso 2) ¿y esto?", (), {})
        normal = claude_chat._prompt_with_attachments("¿Qué tiempo hace?", (), {})
        self.assertIn("<estudio>", desde_estudio)
        self.assertIn("estudio_nueva_escena", desde_estudio)
        self.assertNotIn("<estudio>", normal)

    def test_agy_las_lleva_en_sus_reglas(self):
        from app.executors import antigravity_chat

        reglas = antigravity_chat.PERSONALIDAD_ANTIGRAVITY.format(nombre="Ana")
        self.assertIn("«(Estudio»", reglas)
        self.assertIn("estudio_nueva_escena", reglas)

"""El engine de Estudio: fórmulas, algoritmos, física y el ciclo de las herramientas."""
import asyncio
import math
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import auth, db, tools
from app.config import settings
from app.estudio import algoritmos, capturas, escena, fisica, moleculas, primitivas
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
        await self.run_tool("estudio.paso", texto="Cada término es más pequeño", mostrar=["terminos"])
        segundo = await self.run_tool("estudio.paso", texto="Pero la suma sigue creciendo", mostrar=["sumas"])
        tercero = await self.run_tool(
            "estudio.paso",
            texto="Crece como el logaritmo",
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
        resultado = await self.run_tool("estudio.modelo")
        self.assertEqual(resultado["disponibles"], [])
        self.assertIn("No los inventes", resultado["nota"])

    async def test_ir_a_paso_avisa_a_todas_las_ventanas(self):
        await self.run_tool("estudio.nueva_escena", titulo="Prueba")
        await self.run_tool("estudio.funcion", expresion="x", id="recta")
        await self.run_tool("estudio.paso", texto="Uno")
        await self.run_tool("estudio.paso", texto="Dos")
        await self.run_tool("estudio.ir_a_paso", numero=2)
        self.assertEqual(self.enviados[-1], {"tipo": "estudio_paso", "indice": 1})

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

    def test_una_captura_que_no_se_espera_es_un_404(self):
        respuesta = self.client.post(
            "/api/estudio/capturas/nada", content=b"\xff\xd8x", headers=self.cabeceras
        )
        self.assertEqual(respuesta.status_code, 404)

    def test_un_modelo_inexistente_es_un_404(self):
        respuesta = self.client.get(
            "/api/estudio/modelos/corazon/archivo", headers=self.cabeceras
        )
        self.assertEqual(respuesta.status_code, 404)

"""La forja: herramientas que Vibi se escribe a sí misma y luego ejecuta.

Lo que se comprueba aquí no es que el modelo escriba bien —eso no lo decide
esta suite—, sino lo que pasa con lo que devuelva: qué se rechaza, qué se
prueba antes de guardarse, qué acaba en el catálogo y qué no puede ver un
guion en marcha.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import auth, db, forja, tools
from app.config import settings
from app.executors import agy_mcp
from app.main import create_app

GUION_ECO = '''
def ejecutar(texto, veces=2):
    return {"eco": texto * veces}
'''

MANIFIESTO_ECO = {
    "slug": "repetir-texto",
    "nombre": "Repetir un texto",
    "descripcion": (
        "Repite el texto que le des tantas veces como pidas y lo devuelve junto."
    ),
    "parametros": [
        {
            "nombre": "texto", "tipo": "texto",
            "descripcion": "Lo que se repite", "obligatorio": True,
        },
        {
            "nombre": "veces", "tipo": "entero", "descripcion": "Cuántas veces",
            "obligatorio": False, "por_defecto": 2,
        },
    ],
    "codigo": GUION_ECO,
    "prueba": {"texto": "ab", "veces": 3},
    "notas": "",
}


def respuesta(manifiesto: dict) -> str:
    return json.dumps(manifiesto, ensure_ascii=False)


class ElManifiestoQueDevuelveElModelo(TestCase):
    """Lo que llega es texto de un modelo: se valida antes de guardarlo."""

    def test_un_manifiesto_correcto_se_acepta(self):
        manifiesto = forja.validar_manifiesto(dict(MANIFIESTO_ECO))

        self.assertEqual(manifiesto["slug"], "repetir-texto")
        self.assertEqual(len(manifiesto["parametros"]), 2)

    def test_el_json_se_saca_aunque_venga_en_una_valla_de_codigo(self):
        crudo = f"```json\n{respuesta(MANIFIESTO_ECO)}\n```"

        self.assertEqual(
            forja.objeto_json(crudo)["slug"], MANIFIESTO_ECO["slug"]
        )

    def test_sin_funcion_ejecutar_no_hay_herramienta(self):
        with self.assertRaises(forja.ManifiestoInvalido):
            forja.validar_manifiesto(
                {**MANIFIESTO_ECO, "codigo": "def otra_cosa():\n    return {}\n"}
            )

    def test_una_firma_que_no_encaja_con_los_parametros_se_rechaza(self):
        """El fallo silencioso de verdad: se guarda y revienta al invocarla."""
        with self.assertRaises(forja.ManifiestoInvalido) as fallo:
            forja.validar_manifiesto(
                {**MANIFIESTO_ECO, "codigo": "def ejecutar(otro):\n    return {}\n"}
            )

        self.assertIn("parámetros declarados", str(fallo.exception))

    def test_el_codigo_que_no_compila_se_rechaza_con_la_linea(self):
        with self.assertRaises(forja.ManifiestoInvalido) as fallo:
            forja.validar_manifiesto(
                {
                    **MANIFIESTO_ECO,
                    "codigo": "def ejecutar(texto, veces=2)\n    return {}\n",
                }
            )

        self.assertIn("línea", str(fallo.exception))

    def test_un_tipo_inventado_no_pasa(self):
        with self.assertRaises(forja.ManifiestoInvalido):
            forja.validar_manifiesto(
                {
                    **MANIFIESTO_ECO,
                    "parametros": [
                        {"nombre": "texto", "tipo": "lista", "obligatorio": True}
                    ],
                    "codigo": "def ejecutar(texto):\n    return {}\n",
                }
            )

    def test_cuando_el_modelo_dice_que_no_se_puede_no_se_reintenta(self):
        with self.assertRaises(forja.ForjaFallida):
            forja.validar_manifiesto({"error": "Eso necesita su pantalla"})


class ElGuionEnMarcha(IsolatedAsyncioTestCase):
    """El guion corre en un proceso aparte, y eso es toda la contención."""

    def guion(self, codigo: str) -> dict:
        return {"id": "script.prueba", "version": 1, "codigo": codigo}

    async def test_devuelve_el_resultado_y_lo_que_imprima(self):
        resultado = await forja.ejecutar_guion(
            self.guion(
                'def ejecutar(texto):\n'
                '    print("trabajando")\n'
                '    return {"eco": texto}\n'
            ),
            {"texto": "hola"},
        )

        self.assertEqual(resultado["resultado"], {"eco": "hola"})
        self.assertEqual(resultado["salida"], "trabajando")

    async def test_lo_que_no_es_un_dict_se_envuelve(self):
        resultado = await forja.ejecutar_guion(
            self.guion("def ejecutar():\n    return 42\n"), {}
        )

        self.assertEqual(resultado["resultado"], {"resultado": 42})

    async def test_no_ve_las_credenciales_del_servidor(self):
        """La frontera de verdad: el proceso no tiene delante nada que robar."""
        codigo = (
            "import os\n\n\n"
            "def ejecutar():\n"
            '    return {"clave": os.environ.get("ANTHROPIC_API_KEY", "")}\n'
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-secreta"}):
            resultado = await forja.ejecutar_guion(self.guion(codigo), {})

        self.assertEqual(resultado["resultado"]["clave"], "")

    async def test_un_guion_que_revienta_dice_por_que(self):
        with self.assertRaises(forja.GuionFallido) as fallo:
            await forja.ejecutar_guion(
                self.guion("def ejecutar():\n    raise ValueError('sin datos')\n"), {}
            )

        self.assertIn("sin datos", str(fallo.exception))

    async def test_un_guion_que_no_termina_se_corta(self):
        with patch.object(settings, "forja_timeout_seconds", 1):
            with self.assertRaises(forja.GuionFallido) as fallo:
                await forja.ejecutar_guion(
                    self.guion(
                        "import time\n\n\ndef ejecutar():\n    time.sleep(30)\n"
                    ),
                    {},
                )

        self.assertIn("no terminó", str(fallo.exception))


class ForjarYGuardar(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        for ajuste in (
            patch.object(settings, "db_path", str(root / "vibi.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
        ):
            ajuste.start()
            self.addCleanup(ajuste.stop)
        db.init_db()
        self.user = db.get_or_create_user("ana")

    def escribir(self, *respuestas: str) -> AsyncMock:
        doble = AsyncMock(side_effect=list(respuestas))
        parche = patch("app.executors.claude_forja.escribir", doble)
        parche.start()
        self.addCleanup(parche.stop)
        return doble

    async def test_la_herramienta_se_prueba_antes_de_quedarse_en_el_catalogo(self):
        self.escribir(respuesta(MANIFIESTO_ECO))

        forjada = await forja.forjar(self.user, "Quiero repetir un texto varias veces")

        self.assertEqual(forjada["comprobacion"]["estado"], "ok")
        self.assertEqual(forjada["comprobacion"]["resultado"], {"eco": "ababab"})
        self.assertTrue(forjada["herramienta"]["enabled"])
        self.assertEqual(forjada["herramienta"]["id"], "script.repetir-texto")

    async def test_aparece_en_el_catalogo_y_se_puede_ejecutar(self):
        self.escribir(respuesta(MANIFIESTO_ECO))
        await forja.forjar(self.user, "Quiero repetir un texto varias veces")

        catalogo = {
            herramienta["id"]: herramienta
            for herramienta in tools.list_catalog(self.user["id"])
        }
        ejecucion = await tools.execute(
            "script.repetir-texto", self.user, {"texto": "ab"}
        )

        self.assertEqual(catalogo["script.repetir-texto"]["kind"], "script")
        self.assertEqual(ejecucion["status"], "succeeded")
        self.assertEqual(ejecucion["result"]["resultado"], {"eco": "abab"})

    async def test_la_invocacion_de_un_guion_queda_auditada(self):
        self.escribir(respuesta(MANIFIESTO_ECO))
        await forja.forjar(self.user, "Quiero repetir un texto varias veces")

        await tools.execute("script.repetir-texto", self.user, {"texto": "ab"})
        invocaciones = tools.list_invocations("script.repetir-texto", self.user)

        self.assertEqual(len(invocaciones), 1)
        self.assertEqual(invocaciones[0]["status"], "succeeded")

    async def test_los_argumentos_se_validan_contra_los_parametros_declarados(self):
        self.escribir(respuesta(MANIFIESTO_ECO))
        await forja.forjar(self.user, "Quiero repetir un texto varias veces")

        with self.assertRaises(tools.InvalidToolArguments):
            await tools.execute(
                "script.repetir-texto", self.user, {"inventado": "ab"}
            )

    async def test_un_guion_que_no_pasa_su_prueba_se_reintenta_con_el_error(self):
        roto = {
            **MANIFIESTO_ECO,
            "codigo": (
                "def ejecutar(texto, veces=2):\n"
                "    raise ValueError('me falta algo')\n"
            ),
        }
        doble = self.escribir(respuesta(roto), respuesta(MANIFIESTO_ECO))

        forjada = await forja.forjar(self.user, "Quiero repetir un texto varias veces")

        self.assertEqual(forjada["intentos"], 2)
        self.assertEqual(forjada["comprobacion"]["estado"], "ok")
        self.assertIn("me falta algo", doble.await_args.kwargs["fallo"])

    async def test_si_la_prueba_sigue_fallando_se_guarda_desactivada(self):
        roto = {
            **MANIFIESTO_ECO,
            "codigo": "def ejecutar(texto, veces=2):\n    raise ValueError('no va')\n",
        }
        self.escribir(*[respuesta(roto)] * forja.INTENTOS)

        forjada = await forja.forjar(self.user, "Quiero repetir un texto varias veces")

        self.assertFalse(forjada["herramienta"]["enabled"])
        self.assertEqual(forjada["comprobacion"]["estado"], "fallo")
        with self.assertRaises(tools.ToolDisabled):
            await tools.execute("script.repetir-texto", self.user, {"texto": "ab"})

    async def test_una_respuesta_ilegible_se_devuelve_al_modelo_como_fallo(self):
        doble = self.escribir("aquí tienes tu herramienta", respuesta(MANIFIESTO_ECO))

        forjada = await forja.forjar(self.user, "Quiero repetir un texto varias veces")

        self.assertEqual(forjada["intentos"], 2)
        self.assertIn("objeto JSON", doble.await_args.kwargs["fallo"])

    async def test_agotados_los_intentos_no_se_guarda_nada(self):
        self.escribir(*["no es json"] * forja.INTENTOS)

        with self.assertRaises(forja.ForjaFallida):
            await forja.forjar(self.user, "Quiero repetir un texto varias veces")

        self.assertEqual(forja.listar(self.user["id"]), [])

    async def test_rehacer_conserva_el_identificador_y_sube_la_version(self):
        self.escribir(respuesta(MANIFIESTO_ECO))
        await forja.forjar(self.user, "Quiero repetir un texto varias veces")
        mejorada = {
            **MANIFIESTO_ECO,
            "codigo": (
                "def ejecutar(texto, veces=2):\n"
                '    return {"eco": (texto + " ") * veces}\n'
            ),
        }
        self.escribir(respuesta(mejorada))

        rehecha = await forja.forjar(
            self.user, "Sepáralas con espacios", reemplaza="script.repetir-texto"
        )

        self.assertEqual(rehecha["herramienta"]["id"], "script.repetir-texto")
        self.assertEqual(rehecha["herramienta"]["version"], 2)
        self.assertEqual(len(forja.listar(self.user["id"])), 1)

    async def test_una_forjada_es_solo_de_quien_la_forjo(self):
        self.escribir(respuesta(MANIFIESTO_ECO))
        await forja.forjar(self.user, "Quiero repetir un texto varias veces")
        otro = db.get_or_create_user("pedro")

        catalogo = {herramienta["id"] for herramienta in tools.list_catalog(otro["id"])}

        self.assertNotIn("script.repetir-texto", catalogo)
        with self.assertRaises(tools.ToolNotFound):
            await tools.execute("script.repetir-texto", otro, {"texto": "ab"})

    async def test_el_mismo_nombre_dos_veces_no_pisa_la_anterior(self):
        self.escribir(respuesta(MANIFIESTO_ECO), respuesta(MANIFIESTO_ECO))
        await forja.forjar(self.user, "Quiero repetir un texto varias veces")

        segunda = await forja.forjar(self.user, "Otra parecida pero distinta")

        self.assertEqual(segunda["herramienta"]["id"], "script.repetir-texto-2")

    async def test_la_primitiva_de_forjar_pasa_por_la_auditoria(self):
        self.escribir(respuesta(MANIFIESTO_ECO))

        ejecucion = await tools.execute(
            "herramientas.forjar",
            self.user,
            {"peticion": "Quiero repetir un texto varias veces"},
        )

        self.assertEqual(ejecucion["status"], "succeeded")
        self.assertEqual(
            ejecucion["result"]["herramienta"]["id"], "script.repetir-texto"
        )

    async def test_una_forja_fallida_llega_al_modelo_como_resultado_legible(self):
        self.escribir(*["no es json"] * forja.INTENTOS)

        with self.assertRaises(tools.ToolExecutionFailed):
            await tools.execute(
                "herramientas.forjar",
                self.user,
                {"peticion": "Quiero repetir un texto varias veces"},
            )


class DesdeLaPwa(TestCase):
    """La forja también se pide desde la pantalla de Herramientas."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        for ajuste in (
            patch.object(settings, "db_path", str(root / "vibi.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
            patch.object(
                settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"
            ),
        ):
            ajuste.start()
            self.addCleanup(ajuste.stop)
        db.init_db()
        self.user = db.get_or_create_user("ruben")
        db.set_password_hash(self.user["id"], auth.hash_password("correcta"))
        self.client = TestClient(
            create_app(start_background=False, frontend_dir=root / "missing-dist")
        )
        self.addCleanup(self.client.close)
        token = self.client.post(
            "/api/auth/login",
            json={"nombre": "ruben", "contraseña": "correcta"},
        ).json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    def test_forjar_devuelve_la_herramienta_y_su_comprobacion(self):
        with patch(
            "app.executors.claude_forja.escribir",
            AsyncMock(return_value=respuesta(MANIFIESTO_ECO)),
        ):
            creada = self.client.post(
                "/api/herramientas/forjar",
                json={"peticion": "Quiero repetir un texto varias veces"},
                headers=self.headers,
            )

        self.assertEqual(creada.status_code, 201)
        self.assertEqual(creada.json()["comprobacion"]["estado"], "ok")
        catalogo = self.client.get("/api/herramientas", headers=self.headers).json()
        forjadas = [
            herramienta
            for herramienta in catalogo["herramientas"]
            if herramienta["kind"] == "script"
        ]
        self.assertEqual(len(forjadas), 1)
        # El catálogo va a los dos motores en cada turno: el código no viaja
        # con él, se pide aparte cuando alguien quiere leerlo.
        self.assertNotIn("codigo", forjadas[0])

    def test_el_codigo_se_puede_leer_y_la_herramienta_apagar(self):
        with patch(
            "app.executors.claude_forja.escribir",
            AsyncMock(return_value=respuesta(MANIFIESTO_ECO)),
        ):
            self.client.post(
                "/api/herramientas/forjar",
                json={"peticion": "Quiero repetir un texto varias veces"},
                headers=self.headers,
            )

        guion = self.client.get(
            "/api/herramientas/script.repetir-texto/guion", headers=self.headers
        )
        apagada = self.client.post(
            "/api/herramientas/script.repetir-texto/estado",
            json={"enabled": False},
            headers=self.headers,
        )

        self.assertEqual(guion.status_code, 200)
        self.assertIn("def ejecutar", guion.json()["codigo"])
        self.assertEqual(apagada.status_code, 200)
        self.assertFalse(apagada.json()["enabled"])

    def test_el_guion_de_otro_usuario_no_se_lee(self):
        respuesta_ajena = self.client.get(
            "/api/herramientas/script.lo-que-sea/guion", headers=self.headers
        )

        self.assertEqual(respuesta_ajena.status_code, 404)


class ElPuenteConAgy(unittest.TestCase):
    def test_una_forjada_viaja_con_guion_bajo_y_vuelve_igual(self):
        self.assertEqual(
            agy_mcp.nombre_mcp("script.repetir-texto"), "script_repetir-texto"
        )
        self.assertEqual(
            agy_mcp.id_primitiva("script_repetir-texto"), "script.repetir-texto"
        )

    def test_el_prefijo_a_secas_no_resuelve(self):
        with self.assertRaises(tools.ToolNotFound):
            agy_mcp.id_primitiva("script_")

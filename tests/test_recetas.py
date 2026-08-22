"""Lo que Vibi ha aprendido sobre cómo se maneja cada aplicación.

Una receta no es un recuerdo —«el martes le escribí a Ruffini»— sino una
instrucción reutilizable: qué selector es la lista de chats, cuál el cuadro de
texto, y los huecos que hay que rellenar cada vez. Lo que se prueba aquí es la
contabilidad de esa memoria: guardarla, encontrarla por el nombre que use quien
pregunte, y —sobre todo— **retirarla cuando deja de funcionar**, que es lo que
separa esto de empeorar el sistema.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import recetas  # noqa: E402
from app.config import settings  # noqa: E402


class BaseRecetas(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        parche = patch.object(
            settings, "db_path", str(Path(self.dir) / "prueba.db")
        )
        parche.start()
        self.addCleanup(parche.stop)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))
        recetas.crear_tablas()

    def _guardar(self, app="whatsapp", **kwargs):
        datos = {
            "via": "cdp",
            "contenido": "#pane-side es la lista de chats",
            **kwargs,
        }
        return recetas.guardar(app, **datos)


class GuardarYEncontrar(BaseRecetas):
    def test_lo_guardado_se_recupera(self):
        self._guardar("whatsapp", contenido="#pane-side es la lista")

        receta = recetas.receta_de("whatsapp")

        self.assertIsNotNone(receta)
        self.assertEqual(receta["contenido"], "#pane-side es la lista")
        self.assertEqual(receta["via"], "cdp")

    def test_sin_receta_devuelve_nada(self):
        self.assertIsNone(recetas.receta_de("spotify"))

    def test_se_encuentra_por_como_la_nombre_una_persona(self):
        """La app se apunta como `whatsappdesktop` y se pide como «WhatsApp»."""
        self._guardar("whatsappdesktop")

        self.assertIsNotNone(recetas.receta_de("WhatsApp"))
        self.assertIsNotNone(recetas.receta_de("whatsapp"))

    def test_volver_a_guardar_la_misma_app_la_actualiza(self):
        """Aprender algo nuevo de una app no puede dejar dos recetas suyas."""
        self._guardar("whatsapp", contenido="lo viejo")
        self._guardar("whatsapp", contenido="lo nuevo")

        self.assertEqual(recetas.receta_de("whatsapp")["contenido"], "lo nuevo")
        self.assertEqual(len(recetas.todas()), 1)


class RetirarLaQueYaNoSirve(BaseRecetas):
    """Una receta muerta es peor que no tener ninguna: el agente ejecuta pasos
    que ya no valen y dice que la tarea salió bien. Por eso se retira sola."""

    def test_falla_una_vez_y_sigue_sirviendo(self):
        """Un fallo suelto puede ser la red, o la ventana a medio cargar."""
        self._guardar("whatsapp")

        recetas.registrar_fallo("whatsapp")

        self.assertIsNotNone(recetas.receta_de("whatsapp"))

    def test_a_los_tres_fallos_seguidos_se_retira(self):
        self._guardar("whatsapp")

        for _ in range(recetas.FALLOS_PARA_RETIRAR):
            recetas.registrar_fallo("whatsapp")

        self.assertIsNone(recetas.receta_de("whatsapp"))

    def test_un_acierto_perdona_los_fallos_anteriores(self):
        self._guardar("whatsapp")
        recetas.registrar_fallo("whatsapp")
        recetas.registrar_fallo("whatsapp")

        recetas.marcar_acierto("whatsapp")
        recetas.registrar_fallo("whatsapp")

        self.assertIsNotNone(recetas.receta_de("whatsapp"))

    def test_registrar_fallo_de_una_app_sin_receta_no_revienta(self):
        recetas.registrar_fallo("spotify")


class SoloSeGuardaLoVerificado(BaseRecetas):
    """La regla que sostiene todo lo demás. Si se guardan caminos sin
    comprobar, Vibi aprende una receta inventada y la repite convencida."""

    def test_una_receta_sin_verificar_no_se_guarda(self):
        with self.assertRaises(recetas.RecetaNoVerificada):
            recetas.guardar("whatsapp", via="cdp", contenido="algo", verificada=False)

        self.assertIsNone(recetas.receta_de("whatsapp"))

    def test_una_receta_vacia_no_se_guarda(self):
        for vacio in ("", "   ", None):
            with self.subTest(contenido=vacio):
                with self.assertRaises(recetas.RecetaInvalida):
                    recetas.guardar("whatsapp", via="cdp", contenido=vacio)

    def test_una_via_desconocida_no_se_guarda(self):
        with self.assertRaises(recetas.RecetaInvalida):
            recetas.guardar("whatsapp", via="telepatia", contenido="algo")


class LaHerramientaQueLaPideElModelo(BaseRecetas):
    """`receta_de` es lo que el modelo llama antes de tocar una aplicación.

    Cuesta una llamada (~2,7 s) y ahorra las cuarenta de tanteo. Lo que
    devuelve cuando NO hay receta importa tanto como lo que devuelve cuando la
    hay: es lo que dispara que Vibi diga «esto no lo sé usar todavía».
    """

    def setUp(self):
        super().setUp()
        import asyncio

        from app import tools

        self.tools = tools
        self.correr = asyncio.run
        self.usuario = {"id": "u1", "nombre": "prueba"}

    def _llamar(self, app):
        primitiva = self.tools.PRIMITIVES["recetas.consultar"]
        args = primitiva.input_model.model_validate({"app": app})
        return self.correr(primitiva.handler(self.usuario, args))

    def test_esta_registrada_como_herramienta(self):
        self.assertIn("recetas.consultar", self.tools.PRIMITIVES)

    def test_devuelve_la_receta_cuando_la_hay(self):
        self._guardar("whatsapp", contenido="#pane-side es la lista")

        salida = self._llamar("WhatsApp")

        self.assertTrue(salida["conocida"])
        self.assertIn("#pane-side", salida["receta"])
        self.assertEqual(salida["via"], "cdp")

    def test_cuando_no_la_hay_lo_dice_y_no_falla(self):
        salida = self._llamar("Spotify")

        self.assertFalse(salida["conocida"])
        self.assertIsNone(salida.get("receta"))

    def test_cuando_no_la_hay_dice_que_lo_aprendido_se_puede_guardar(self):
        """Sin esto el modelo explora, acierta y tira el hallazgo a la basura."""
        salida = self._llamar("Spotify")

        self.assertIn("aviso", salida)
        self.assertTrue(salida["aviso"].strip())


class AprenderYOlvidar(BaseRecetas):
    """Guardar exige aportar la comprobación, no solo afirmarla.

    Que el modelo marque una casilla de «sí, lo verifiqué» no cuesta nada y por
    tanto no prueba nada. Pedirle que escriba QUÉ vio es más difícil de
    inventar, y además deja el motivo apuntado para cuando haya que auditar por
    qué se guardó una receta mala.
    """

    def setUp(self):
        super().setUp()
        import asyncio

        from app import tools

        self.tools = tools
        self.correr = asyncio.run
        self.usuario = {"id": "u1", "nombre": "prueba"}

    def _llamar(self, nombre, **campos):
        primitiva = self.tools.PRIMITIVES[nombre]
        args = primitiva.input_model.model_validate(campos)
        return self.correr(primitiva.handler(self.usuario, args))

    def test_aprender_guarda_lo_comprobado(self):
        salida = self._llamar(
            "recetas.aprender",
            app="WhatsApp",
            via="cdp",
            contenido="#pane-side es la lista de chats",
            comprobacion="Releí el chat y el mensaje aparecía enviado a las 23:00",
        )

        self.assertTrue(salida["guardada"])
        self.assertIsNotNone(recetas.receta_de("whatsapp"))

    def test_sin_comprobacion_no_guarda(self):
        for vacia in ("", "   "):
            with self.subTest(comprobacion=vacia):
                salida = self._llamar(
                    "recetas.aprender",
                    app="WhatsApp",
                    via="cdp",
                    contenido="#pane-side",
                    comprobacion=vacia,
                )
                self.assertFalse(salida["guardada"])
                self.assertIsNone(recetas.receta_de("whatsapp"))

    def test_la_comprobacion_queda_apuntada(self):
        self._llamar(
            "recetas.aprender",
            app="WhatsApp",
            via="cdp",
            contenido="#pane-side",
            comprobacion="El mensaje aparecía en el chat",
        )

        self.assertEqual(
            recetas.receta_de("whatsapp")["comprobacion"],
            "El mensaje aparecía en el chat",
        )

    def test_olvidar_retira_la_receta(self):
        self._guardar("whatsapp")

        salida = self._llamar("recetas.olvidar", app="WhatsApp")

        self.assertTrue(salida["olvidada"])
        self.assertIsNone(recetas.receta_de("whatsapp"))


class LaRecetaLlegaSinQueLaPida(BaseRecetas):
    """La herramienta `recetas_consultar` existe y el modelo no la llama.

    Medido el 22/08/2026: cero invocaciones en tres tareas seguidas sobre
    WhatsApp, con el esquema publicado y disponible. Pedírselo por escrito en
    la descripción de la herramienta no funciona —`agy` no le da los esquemas
    completos en el prompt— y fiarlo a una regla tampoco: ya pasó con el
    catálogo de herramientas.

    Así que no se le pide: cuando toca una aplicación de la que sí sabemos
    algo, la receta le llega dentro de la respuesta de la herramienta que ya
    estaba usando. Cero llamadas de más y nada que recordar.
    """

    def setUp(self):
        super().setUp()
        import asyncio

        from app import tools

        self.tools = tools
        self.correr = asyncio.run
        self.usuario = {"id": "u1", "nombre": "prueba"}

    def _llamar(self, nombre, resultado_del_nodo, **campos):
        """`_dispatch_device` no devuelve lo del nodo a pelo: lo envuelve en
        `{device, state, message, result}`. Simularlo plano es inventarse una
        forma que no existe, y fue justo lo que dejó pasar el fallo."""
        primitiva = self.tools.PRIMITIVES[nombre]
        args = primitiva.input_model.model_validate(campos)

        async def falso(*_a, **_k):
            return {
                "device": {"id": "n1"},
                "state": "completada",
                "message": None,
                "result": resultado_del_nodo,
            }

        with patch.object(self.tools, "resolve_device", return_value={"id": "n1"}), \
             patch.object(self.tools, "_dispatch_device", falso):
            return self.correr(primitiva.handler(self.usuario, args))

    def test_mirar_una_ventana_conocida_trae_su_receta(self):
        self._guardar("whatsappdesktop", contenido="#pane-side es la lista")

        salida = self._llamar(
            "devices.ui_snapshot",
            {"arbol": "...", "ventana": "WhatsApp"},
            window="WhatsApp",
        )

        self.assertIn("#pane-side", salida["receta"])

    def test_una_ventana_desconocida_no_trae_nada_ni_falla(self):
        salida = self._llamar(
            "devices.ui_snapshot",
            {"arbol": "...", "ventana": "Bloc de notas"},
            window="Bloc de notas",
        )

        self.assertNotIn("receta", salida)
        self.assertEqual(salida["result"]["arbol"], "...")

    def test_la_pista_vale_aunque_el_nodo_no_conteste(self):
        """El nodo puede fallar o devolver vacío; la ventana la pediste tú."""
        self._guardar("whatsappdesktop", contenido="#pane-side es la lista")

        salida = self._llamar("devices.ui_snapshot", None, window="WhatsApp")

        self.assertIn("#pane-side", salida["receta"])

    def test_hablar_por_dentro_con_una_app_conocida_trae_su_receta(self):
        self._guardar("whatsappdesktop", contenido="#pane-side es la lista")

        salida = self._llamar(
            "devices.web",
            {"resultado": "ok"},
            app="WhatsApp",
            javascript="1",
        )

        self.assertIn("#pane-side", salida["receta"])

    def test_no_pisa_lo_que_ya_traia_la_respuesta(self):
        """La receta se añade; el resultado del nodo se respeta tal cual."""
        self._guardar("whatsappdesktop")

        salida = self._llamar(
            "devices.ui_snapshot",
            {"arbol": "el arbol de verdad", "ventana": "WhatsApp"},
            window="WhatsApp",
        )

        self.assertEqual(salida["result"]["arbol"], "el arbol de verdad")
        self.assertEqual(salida["state"], "completada")


class LaRecetaNoSeRepiteEnCadaLlamada(BaseRecetas):
    """Colgarla de cada respuesta la mandaba una vez por herramienta.

    Medido el 22/08/2026 en un turno de WhatsApp: nueve llamadas, nueve copias
    del mismo bloque de 1670 caracteres —unos 4.000 tokens pagados por nada—.
    El modelo no necesita releerla: la conversación con `agy` conserva el
    historial, así que la primera vez va entera y el resto va una línea que le
    dice dónde mirar.
    """

    def setUp(self):
        super().setUp()
        import asyncio

        from app import tools

        self.tools = tools
        self.correr = asyncio.run
        self.usuario = {"id": "u1", "nombre": "prueba"}
        self.tools._recetas_dadas.clear()

    def _llamar(self, nombre, conversacion="c1", **campos):
        primitiva = self.tools.PRIMITIVES[nombre]
        args = primitiva.input_model.model_validate(campos)

        async def falso(*_a, **_k):
            return {
                "device": {"id": "n1"},
                "state": "completada",
                "message": None,
                "result": {"resultado": "ok"},
            }

        with patch.object(self.tools, "resolve_device", return_value={"id": "n1"}), \
             patch.object(self.tools, "_dispatch_device", falso), \
             patch.object(
                 self.tools.db, "get_active_conversation",
                 return_value={"id": conversacion},
             ):
            return self.correr(primitiva.handler(self.usuario, args))

    def test_la_primera_vez_llega_entera(self):
        self._guardar("whatsappdesktop", contenido="#pane-side es la lista")

        salida = self._llamar("devices.web", app="WhatsApp", javascript="1")

        self.assertIn("#pane-side", salida["receta"])

    def test_la_segunda_vez_solo_le_dice_donde_mirar(self):
        self._guardar("whatsappdesktop", contenido="#pane-side es la lista")
        self._llamar("devices.web", app="WhatsApp", javascript="1")

        salida = self._llamar("devices.web", app="WhatsApp", javascript="2")

        self.assertNotIn("receta", salida)
        self.assertIn("WhatsApp", salida["receta_ya_dada"])

    def test_en_otra_conversacion_vuelve_a_llegar_entera(self):
        """Al reiniciar, el historial se queda atrás y con él la receta."""
        self._guardar("whatsappdesktop", contenido="#pane-side es la lista")
        self._llamar("devices.web", app="WhatsApp", javascript="1")

        salida = self._llamar(
            "devices.web", conversacion="c2", app="WhatsApp", javascript="1"
        )

        self.assertIn("#pane-side", salida["receta"])

    def test_otra_aplicacion_trae_la_suya(self):
        self._guardar("whatsappdesktop", contenido="#pane-side es la lista")
        self._guardar("spotify", contenido="la barra de buscar es .search")
        self._llamar("devices.web", app="WhatsApp", javascript="1")

        salida = self._llamar("devices.web", app="Spotify", javascript="1")

        self.assertIn(".search", salida["receta"])


class AbrirLaAppTraeLaReceta(BaseRecetas):
    """La receta tiene que llegar por el camino que ella misma manda usar.

    Medido el 22/08/2026: la de WhatsApp dice «se maneja por CDP, no por el
    árbol», pero solo se inyectaba al mirar el árbol o al ejecutar JavaScript.
    O sea que para recibirla había que desobedecerla. `apps.launch` es el
    primer sitio donde se nombra la aplicación, y ahí es donde debe llegar.
    """

    def setUp(self):
        super().setUp()
        import asyncio

        from app import tools

        self.tools = tools
        self.correr = asyncio.run
        self.usuario = {"id": "u1", "nombre": "prueba"}
        self.tools._recetas_dadas.clear()

    def _abrir(self, app):
        primitiva = self.tools.PRIMITIVES["devices.launch_app"]
        args = primitiva.input_model.model_validate({"app": app})

        async def falso(*_a, **_k):
            return {"estado": "completada", "mensaje": None,
                    "resultado": {"status": "launched"}}

        with patch.object(self.tools, "resolve_device", return_value={"id": "n1"}), \
             patch.object(
                 self.tools, "_serialize_device", return_value={"id": "n1"}
             ), \
             patch.object(self.tools.nodes, "dispatch", falso), \
             patch.object(
                 self.tools.db, "get_active_conversation",
                 return_value={"id": "c1"},
             ):
            return self.correr(primitiva.handler(self.usuario, args))

    def test_abrir_una_app_conocida_trae_su_receta(self):
        self._guardar("whatsappdesktop", contenido="#pane-side es la lista")

        salida = self._abrir("WhatsApp")

        self.assertIn("#pane-side", salida["receta"])

    def test_abrir_una_app_desconocida_no_falla(self):
        salida = self._abrir("Bloc de notas")

        self.assertNotIn("receta", salida)
        self.assertEqual(salida["state"], "completada")

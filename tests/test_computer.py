"""El ratón y el teclado: de lo que ve el modelo a lo que hace la máquina."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from morgana_node import capabilities, computer, screen  # noqa: E402
from morgana_node.config import NodeConfig  # noqa: E402

from app import nodes, tools

# Una pantalla 1920x1080 a la izquierda de la principal, vista en una imagen de
# 1568x882. El origen negativo es lo que hace inútil pedirle coordenadas de
# escritorio al modelo.
MAPA = "-1920,0,1920,1080,1568,882"


def _completado(codigo: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["usecomputer"], returncode=codigo, stdout=stdout, stderr=stderr
    )


class MapaDeLaUltimaCaptura(TestCase):
    def setUp(self):
        screen.olvidar_mapa()
        self.addCleanup(screen.olvidar_mapa)

    def test_la_captura_deja_el_mapa_que_usecomputer_entiende(self):
        screen._recordar_mapa(
            {
                "ancho": 1568,
                "alto": 882,
                "ancho_real": 1920,
                "alto_real": 1080,
                "origen_x": -1920,
                "origen_y": 0,
            }
        )
        self.assertEqual(screen.mapa_actual(), MAPA)

    def test_sin_tamano_de_imagen_no_se_inventa_un_mapa(self):
        self.assertEqual(screen._recordar_mapa({"ancho": 0, "alto": 0}), "")
        self.assertEqual(screen.mapa_actual(), "")


class SinMirarNoSeToca(TestCase):
    def setUp(self):
        screen.olvidar_mapa()
        self.addCleanup(screen.olvidar_mapa)

    def test_pinchar_sin_captura_previa_explica_que_hay_que_mirar(self):
        with self.assertRaisesRegex(computer.ErrorOrdenador, "mira primero"):
            computer.clic(100, 200)

    def test_teclear_no_necesita_captura(self):
        """El teclado escribe donde esté el foco: no hay nada que traducir."""
        with patch.object(
            computer, "_ejecutar", return_value=""
        ) as ejecutar:
            computer.teclear("hola")
        ejecutar.assert_called_once()


class CoordenadasDeLaImagen(TestCase):
    def setUp(self):
        screen.olvidar_mapa()
        self.addCleanup(screen.olvidar_mapa)
        screen._recordar_mapa(
            {
                "ancho": 1568,
                "alto": 882,
                "ancho_real": 1920,
                "alto_real": 1080,
                "origen_x": -1920,
                "origen_y": 0,
            }
        )

    def test_el_clic_viaja_con_el_mapa_de_la_captura(self):
        with patch.object(computer, "_ejecutar", return_value="") as ejecutar:
            resultado = computer.clic(400, 220, "right", 2, ("ctrl",))

        argumentos = ejecutar.call_args[0][0]
        self.assertEqual(argumentos[0], "click")
        self.assertEqual(argumentos[argumentos.index("--coord-map") + 1], MAPA)
        self.assertEqual(argumentos[argumentos.index("-x") + 1], "400")
        self.assertEqual(argumentos[argumentos.index("--button") + 1], "right")
        self.assertEqual(argumentos[argumentos.index("--count") + 1], "2")
        self.assertEqual(argumentos[argumentos.index("--modifier") + 1], "ctrl")
        self.assertEqual(resultado["x"], 400)

    def test_arrastrar_manda_los_dos_puntos_en_el_formato_de_la_cli(self):
        with patch.object(computer, "_ejecutar", return_value="") as ejecutar:
            computer.arrastrar(10, 20, 30, 40)

        argumentos = ejecutar.call_args[0][0]
        self.assertEqual(argumentos[:3], ["drag", "10,20", "30,40"])

    def test_el_scroll_traduce_el_punto_porque_at_no_acepta_mapa(self):
        with patch.object(computer, "_ejecutar", return_value="") as ejecutar:
            computer.desplazar("down", 5, (784, 441))

        argumentos = ejecutar.call_args[0][0]
        self.assertEqual(argumentos[:3], ["scroll", "down", "5"])
        # El centro de la imagen es el centro de esa pantalla, que empieza en
        # -1920: 784/1568 * 1920 - 1920 = -960.
        self.assertEqual(argumentos[argumentos.index("--at") + 1], "-960,540")

    def test_un_clic_simple_no_arrastra_flags_que_no_hacen_falta(self):
        """`--count 1` tumba el binario de Windows y no aporta nada."""
        with patch.object(computer, "_ejecutar", return_value="") as ejecutar:
            computer.clic(10, 10)

        self.assertNotIn("--count", ejecutar.call_args[0][0])

    def test_un_boton_que_no_existe_se_rechaza_antes_de_ejecutar_nada(self):
        with patch.object(computer, "_ejecutar") as ejecutar:
            with self.assertRaisesRegex(computer.ErrorOrdenador, "botón"):
                computer.clic(1, 1, "izquierdo")
        ejecutar.assert_not_called()


class Teclado(TestCase):
    def test_lo_que_no_cabe_en_la_linea_de_comandos_va_por_stdin(self):
        largo = "a" * (computer.MAX_TEXTO_ARGUMENTO + 1)
        with patch.object(computer, "_ejecutar", return_value="") as ejecutar:
            computer.teclear(largo)

        argumentos, opciones = ejecutar.call_args
        self.assertEqual(argumentos[0], ["type", "--stdin"])
        self.assertEqual(opciones["entrada"], largo)

    def test_repetir_una_tecla_es_pulsarla_varias_veces_y_no_un_flag(self):
        """`--count` se lleva por delante el binario de Windows."""
        with patch.object(computer, "_ejecutar", return_value="") as ejecutar:
            resultado = computer.pulsar("down", 4)

        self.assertEqual(ejecutar.call_count, 4)
        for llamada in ejecutar.call_args_list:
            self.assertEqual(llamada[0][0], ["press", "down"])
        self.assertEqual(resultado["veces"], 4)


class FallosLegibles(TestCase):
    def test_el_crash_del_binario_no_se_cuenta_como_error_del_ordenador(self):
        # Con signo cuando Python lanza el ejecutable, sin él cuando lanza el
        # `.cmd` de npm: los dos son la misma caída.
        for codigo in (-1073741795, 3221225501):
            with self.subTest(codigo=codigo):
                motivo = computer._motivo(_completado(codigo))
                self.assertIn("se ha caído", motivo)
                self.assertIn("teclado", motivo)
                self.assertIn("npm install -g usecomputer", motivo)

    def test_los_codigos_de_la_cli_se_traducen(self):
        motivo = computer._motivo(
            _completado(1, stderr="error: MissingMainKey (EVENT_POST_FAILED)")
        )
        self.assertIn("ctrl+s", motivo)

    def test_un_fallo_desconocido_conserva_lo_que_dijo_la_cli(self):
        motivo = computer._motivo(_completado(1, stderr="algo raro pasó"))
        self.assertEqual(motivo, "algo raro pasó")


class LocalizarElBinario(TestCase):
    def test_la_variable_manda_sobre_el_path(self):
        with patch.dict(
            "os.environ", {computer.VARIABLE_BINARIO: __file__}, clear=False
        ):
            self.assertEqual(computer.argv_base(), [__file__])

    def test_una_variable_que_apunta_a_la_nada_lo_dice(self):
        with patch.dict(
            "os.environ",
            {computer.VARIABLE_BINARIO: "/no/existe/usecomputer"},
            clear=False,
        ):
            with self.assertRaisesRegex(computer.ErrorOrdenador, "no existe"):
                computer.argv_base()

    def test_sin_binario_ni_npx_se_explica_como_instalarlo(self):
        with (
            patch.dict("os.environ", {computer.VARIABLE_BINARIO: ""}, clear=False),
            patch.object(computer.shutil, "which", return_value=None),
            patch.object(computer, "_npm_global", return_value=None),
            # Este equipo sí tiene npx declarado, y con él la CLI se puede
            # descargar al vuelo: para probar el caso sin salida hay que
            # quitarlo también.
            patch.object(computer, "_npx", return_value=None),
        ):
            with self.assertRaisesRegex(computer.ErrorOrdenador, "npm install -g"):
                computer.argv_base()


class CapacidadesDelAgente(TestCase):
    def setUp(self):
        self.config = NodeConfig(
            url="https://morgana.local",
            node_id="node-1",
            token="token",
            nombre="PC",
            projects_root=".",
        )

    def test_el_agente_enruta_cada_accion_a_su_funcion(self):
        casos = {
            "screen.click": ("clic", {"x": 1, "y": 2}),
            "screen.move": ("mover", {"x": 1, "y": 2}),
            "screen.drag": (
                "arrastrar",
                {"desde_x": 1, "desde_y": 2, "hasta_x": 3, "hasta_y": 4},
            ),
            "screen.scroll": ("desplazar", {"direccion": "down"}),
            "screen.type": ("teclear", {"texto": "hola"}),
            "screen.key": ("pulsar", {"tecla": "enter"}),
        }
        for capacidad, (funcion, argumentos) in casos.items():
            with self.subTest(capacidad=capacidad):
                with patch.object(
                    computer, funcion, return_value={"accion": funcion}
                ) as doble:
                    resultado = capabilities.run(self.config, capacidad, argumentos)
                doble.assert_called_once()
                self.assertEqual(resultado["accion"], funcion)

    def test_el_fallo_de_usecomputer_llega_como_rechazo_de_capacidad(self):
        with patch.object(
            computer, "clic", side_effect=computer.ErrorOrdenador("mira primero")
        ):
            with self.assertRaisesRegex(capabilities.CapabilityError, "mira primero"):
                capabilities.run(self.config, "screen.click", {"x": 1, "y": 1})


class DeclaracionEnLosDosLados(TestCase):
    def test_cada_capacidad_esta_publicada_en_los_tres_sitios(self):
        for capacidad in nodes.CAPACIDADES_ENTRADA:
            with self.subTest(capacidad=capacidad):
                self.assertIn(capacidad, capabilities.HANDLERS)
                self.assertIn(capacidad, nodes.CAPABILITIES)
                self.assertNotIn(capacidad, nodes.CAPACIDADES_LECTURA)

        for primitiva in (
            "devices.click",
            "devices.move",
            "devices.drag",
            "devices.scroll",
            "devices.type",
            "devices.key",
        ):
            with self.subTest(primitiva=primitiva):
                self.assertIn(primitiva, tools.PRIMITIVES)

    def test_mover_el_puntero_no_pesa_lo_mismo_que_pinchar(self):
        with patch.object(nodes.taint.registro, "contaminado", return_value=False):
            self.assertEqual(nodes.evaluar_riesgo("u", "screen.move", {}), "bajo")
            self.assertEqual(nodes.evaluar_riesgo("u", "screen.click", {}), "medio")
        with patch.object(nodes.taint.registro, "contaminado", return_value=True):
            # Con el contexto contaminado, un clic puede ser el brazo de algo
            # que se leyó en una web.
            self.assertEqual(nodes.evaluar_riesgo("u", "screen.click", {}), "alto")
            self.assertEqual(nodes.evaluar_riesgo("u", "screen.type", {}), "alto")


class PrimitivasPublicas(IsolatedAsyncioTestCase):
    def setUp(self):
        self.node = {
            "id": "node-1",
            "user_id": "u",
            "nombre": "PC",
            "plataforma": "Windows 11",
            "estado": "activo",
            "shell_habilitado": 1,
            "capacidades": ["screen.click"],
            "last_seen": None,
            "created_at": 0.0,
        }
        self.outcome = {"estado": "ok", "resultado": {"accion": "clic"}}

    async def _ejecutar(self, primitiva: str, argumentos: dict):
        with (
            patch.object(tools, "resolve_device", return_value=self.node),
            patch.object(
                nodes, "dispatch", AsyncMock(return_value=self.outcome)
            ) as dispatch,
        ):
            primitive = tools.PRIMITIVES[primitiva]
            parsed = primitive.input_model.model_validate(argumentos)
            await primitive.handler({"id": "u"}, parsed)
        return dispatch.await_args[0]

    async def test_el_clic_traduce_los_nombres_al_vocabulario_del_nodo(self):
        _, _, capacidad, enviados = await self._ejecutar(
            "devices.click",
            {"x": 400, "y": 220, "button": "right", "count": 2,
             "modifiers": "ctrl+shift"},
        )
        self.assertEqual(capacidad, "screen.click")
        self.assertEqual(
            enviados,
            {
                "x": 400,
                "y": 220,
                "boton": "right",
                "veces": 2,
                "modificadores": ["ctrl", "shift"],
            },
        )

    async def test_la_tecla_viaja_con_sus_repeticiones(self):
        _, _, capacidad, enviados = await self._ejecutar(
            "devices.key", {"key": "ctrl+s", "count": 3}
        )
        self.assertEqual(capacidad, "screen.key")
        self.assertEqual(enviados["tecla"], "ctrl+s")
        self.assertEqual(enviados["veces"], 3)

    async def test_las_coordenadas_negativas_no_pasan_la_validacion(self):
        primitive = tools.PRIMITIVES["devices.click"]
        with self.assertRaises(Exception):
            primitive.input_model.model_validate({"x": -5, "y": 10})

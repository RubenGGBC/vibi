"""El nodo contándole al servidor lo que Windows le notifica.

Hasta ahora el nodo solo hablaba cuando le preguntaban: recibía órdenes y
devolvía resultados. Esto es lo primero que dice por su cuenta, así que lo que
se prueba es que no se pase — que no hable antes de tiempo, que un fallo de
lectura no tumbe la conexión, y que no repita.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import avisos  # noqa: E402
from vibi_node.config import NodeConfig  # noqa: E402


class _Conexion:
    """Un websocket de mentira que guarda lo que se le manda."""

    def __init__(self):
        self.enviados = []

    async def send(self, crudo):
        self.enviados.append(json.loads(crudo))

    def mensajes(self, tipo):
        return [m for m in self.enviados if m.get("tipo") == tipo]


def _aviso(id_, app="WhatsApp", titulo="Ana", cuerpo="¿Quedamos?"):
    return avisos.Aviso(id=id_, app=app, titulo=titulo, cuerpo=cuerpo, cuando="")


class _VigiaDePrueba:
    """El mismo criterio que el de verdad, sin depender de WinRT.

    Callarse en el primer vistazo es parte de lo que se prueba aquí, así que se
    replica en vez de sustituirse por algo que lo diga todo.
    """

    def __init__(self):
        self._vistas = set()
        self._estrenado = False

    def novedades(self, lista):
        nuevas = [a for a in lista if a.id not in self._vistas]
        self._vistas.update(a.id for a in lista)
        if not self._estrenado:
            self._estrenado = True
            return []
        return nuevas


class Vigilar(IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = NodeConfig(
            url="https://vibi.local", node_id="n", token="t",
            nombre="PC", projects_root=".", inbox_root=".",
        )
        self.conexion = _Conexion()

    async def _correr(self, lecturas, vueltas=None):
        """Deja correr el vigilante tantas vueltas como lecturas haya."""
        vueltas = vueltas if vueltas is not None else len(lecturas)
        # Agotar un `side_effect` lanza StopIteration, y eso dentro de un
        # futuro da un error que no tiene nada que ver con lo que se prueba.
        # Al terminar la lista se repite la última lectura para siempre.
        restantes = list(lecturas)

        def leer_de_mentira():
            actual = restantes.pop(0) if len(restantes) > 1 else restantes[0]
            if isinstance(actual, Exception):
                raise actual
            return actual

        lector = MagicMock(side_effect=leer_de_mentira)
        with patch.object(avisos, "INTERVALO", 0), \
             patch.object(avisos, "ESPERA_TRAS_FALLO", 0), \
             patch.object(avisos, "_leer", lector), \
             patch.object(avisos, "disponible", return_value=True), \
             patch.object(avisos, "_vigia", _VigiaDePrueba):
            tarea = asyncio.create_task(
                avisos.vigilar(self.conexion, self.config)
            )
            # `_leer` se llama en un hilo de verdad, así que hay que dejar
            # pasar tiempo de reloj y no solo ceder el bucle.
            for _ in range(300):
                if lector.call_count >= vueltas:
                    break
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.02)
            tarea.cancel()
            try:
                await tarea
            except asyncio.CancelledError:
                pass
        return lector

    async def test_lo_que_ya_estaba_al_conectar_no_se_manda(self):
        """Las notificaciones viejas del centro no son noticia."""
        await self._correr([[_aviso(1), _aviso(2)]])
        self.assertEqual(self.conexion.mensajes("aviso"), [])

    async def test_una_notificacion_nueva_se_manda(self):
        await self._correr([[_aviso(1)], [_aviso(1), _aviso(2)]])
        mandados = self.conexion.mensajes("aviso")
        self.assertEqual(len(mandados), 1)
        aviso = mandados[0]["aviso"]
        self.assertEqual(aviso["app"], "WhatsApp")
        self.assertEqual(aviso["titulo"], "Ana")
        self.assertEqual(aviso["cuerpo"], "¿Quedamos?")

    async def test_no_se_repite_lo_ya_mandado(self):
        await self._correr([[_aviso(1)], [_aviso(1)], [_aviso(1)]])
        self.assertEqual(self.conexion.mensajes("aviso"), [])

    async def test_varias_de_golpe_van_en_mensajes_distintos(self):
        await self._correr([[], [_aviso(1), _aviso(2), _aviso(3)]])
        self.assertEqual(len(self.conexion.mensajes("aviso")), 3)

    async def test_un_fallo_al_leer_no_tumba_el_vigilante(self):
        """Windows puede negarse un momento; no es motivo para callar para siempre."""
        lector = await self._correr(
            [[], RuntimeError("Windows dijo que no"), [_aviso(9)]], vueltas=3
        )
        # Siguió leyendo después del error —de eso va la prueba— así que lo que
        # importa es que llegó a la tercera lectura y que el aviso salió.
        self.assertGreaterEqual(lector.call_count, 3)
        self.assertEqual(len(self.conexion.mensajes("aviso")), 1)

    async def test_sin_notificaciones_no_se_dice_nada(self):
        await self._correr([[], [], []])
        self.assertEqual(self.conexion.enviados, [])


class SinSoporte(IsolatedAsyncioTestCase):
    async def test_donde_no_se_puede_leer_el_vigilante_se_retira(self):
        """En un Mac, o sin permiso, no se queda dando vueltas en balde."""
        config = NodeConfig(
            url="u", node_id="n", token="t", nombre="Mac",
            projects_root=".", inbox_root=".",
        )
        conexion = _Conexion()
        with patch.object(avisos, "disponible", return_value=False):
            await asyncio.wait_for(avisos.vigilar(conexion, config), timeout=1)
        self.assertEqual(conexion.enviados, [])

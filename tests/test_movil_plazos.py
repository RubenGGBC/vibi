"""Por voz nadie espera 45 segundos: lo que no contesta enseguida, falla."""
import asyncio
import time
from unittest.mock import AsyncMock, patch

from app import movil, nodes
from tests.test_movil import CAPACIDADES, MovilTestCase


class PlazosDeLasOrdenes(MovilTestCase):
    def test_orden_de_voz_lleva_plazo_corto(self):
        self.alta("Galaxy", CAPACIDADES)
        respuesta = {"estado": "ok", "resultado": {}}
        with patch.object(nodes, "dispatch", AsyncMock(return_value=respuesta)) as dispatch:
            asyncio.run(movil.ejecutar(self.user, "movil_musica", {"accion": "pausar"}))
        self.assertEqual(dispatch.call_args.kwargs["plazo_segundos"], movil.PLAZO_ORDEN_S)
        self.assertLessEqual(movil.PLAZO_ORDEN_S, 10)

    def test_movil_mudo_falla_dentro_del_plazo(self):
        node = self.alta("Galaxy", CAPACIDADES)
        enviados = []

        async def enviar(node_id, payload):
            enviados.append(payload)
            return True

        async def probar():
            inicio = time.monotonic()
            with patch.object(nodes.manager, "is_online", return_value=True), patch.object(
                nodes.manager, "send", enviar
            ):
                respuesta = await nodes.dispatch(
                    self.user,
                    node,
                    "movil.media",
                    {"accion": "pausar"},
                    queue_if_offline=False,
                    plazo_segundos=0.2,
                )
            return respuesta, time.monotonic() - inicio

        respuesta, tardado = asyncio.run(probar())
        self.assertEqual(respuesta["estado"], "timeout")
        self.assertLess(tardado, 1)
        self.assertGreater(enviados[0]["caduca_en"], time.time() - 5)

    def test_orden_sin_plazo_no_cambia(self):
        node = self.alta("PC", ["ping"])
        enviados = []

        async def enviar(node_id, payload):
            enviados.append(payload)
            return True

        async def probar():
            with patch.object(nodes.manager, "is_online", return_value=True), patch.object(
                nodes.manager, "send", enviar
            ):
                return await nodes.dispatch(self.user, node, "ping", {}, queue_if_offline=False)

        asyncio.run(probar())
        self.assertNotIn("caduca_en", enviados[0])

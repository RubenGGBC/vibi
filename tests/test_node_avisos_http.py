"""La puerta local por la que cualquier proceso de la máquina avisa a Vibi.

Lo que se prueba es el contrato con quien llama —un hook, un script—, que es
lo único que no podemos cambiar después sin romperle el suyo: qué acepta, qué
rechaza con motivo, y que un aviso que no llega se diga que no llegó.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import avisos_http  # noqa: E402


class _Conexion:
    def __init__(self):
        self.enviados = []

    async def send(self, crudo):
        self.enviados.append(crudo)


def _pedir(payload: bytes, ruta="/aviso", metodo="POST"):
    """Una petición contra la app ASGI, sin abrir ningún puerto."""
    import httpx

    async def escenario():
        transporte = httpx.ASGITransport(app=avisos_http._construir_app())
        async with httpx.AsyncClient(
            transport=transporte, base_url="http://local"
        ) as cliente:
            return await cliente.request(metodo, ruta, content=payload)

    return asyncio.run(escenario())


def _json(**campos) -> bytes:
    import json

    return json.dumps(campos).encode()


class Contrato(TestCase):
    def setUp(self):
        avisos_http.olvidar()
        self.addCleanup(avisos_http.olvidar)

    def test_un_aviso_normal_se_entrega(self):
        with patch.object(avisos_http, "_entregar", return_value=True) as entregar:
            respuesta = _pedir(
                _json(app="Claude Code", titulo="", cuerpo="Ha terminado")
            )
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.json()["entregado"])
        self.assertEqual(
            entregar.call_args[0][0],
            {"app": "Claude Code", "titulo": "", "cuerpo": "Ha terminado"},
        )

    def test_sin_titulo_ni_cuerpo_se_rechaza_con_motivo(self):
        """Quien llama es un script: se le dice por qué, en vez de tragárselo
        callado y que crea que avisó."""
        with patch.object(avisos_http, "_entregar", return_value=True) as entregar:
            respuesta = _pedir(_json(app="Algo"))
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("titulo", respuesta.json()["motivo"])
        entregar.assert_not_called()

    def test_sin_conexion_con_vibi_responde_503(self):
        """No se encola para más tarde: el hook se entera de que no llegó."""
        respuesta = _pedir(_json(cuerpo="Ha terminado"))
        self.assertEqual(respuesta.status_code, 503)
        self.assertFalse(respuesta.json()["entregado"])

    def test_los_campos_se_normalizan_y_se_recortan(self):
        with patch.object(avisos_http, "_entregar", return_value=True) as entregar:
            _pedir(_json(app="  Claude   Code ", cuerpo="x" * 5_000))
        aviso = entregar.call_args[0][0]
        self.assertEqual(aviso["app"], "Claude Code")
        self.assertLessEqual(len(aviso["cuerpo"]), avisos_http.MAX_CAMPO)

    def test_un_campo_de_mas_se_rechaza_diciendo_cual(self):
        """El contrato es cerrado: si alguien manda `mensaje` en vez de
        `cuerpo`, mejor que falle ahora y no que su aviso desaparezca."""
        respuesta = _pedir(_json(cuerpo="Ha terminado", mensaje="otra cosa"))
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("mensaje", respuesta.json()["motivo"])

    def test_lo_que_no_es_json_se_rechaza(self):
        respuesta = _pedir(b"esto no es json")
        self.assertEqual(respuesta.status_code, 400)

    def test_otra_ruta_no_existe(self):
        respuesta = _pedir(_json(cuerpo="x"), ruta="/otra")
        self.assertEqual(respuesta.status_code, 404)

    def test_un_get_no_vale(self):
        respuesta = _pedir(b"", metodo="GET")
        self.assertEqual(respuesta.status_code, 405)


class Entrega(TestCase):
    """El salto del hilo del servidor HTTP al hilo donde vive el WebSocket."""

    def setUp(self):
        avisos_http.olvidar()
        self.addCleanup(avisos_http.olvidar)

    def test_lo_registrado_llega_al_websocket(self):
        conexion = _Conexion()

        async def escenario():
            avisos_http.registrar(conexion, asyncio.get_running_loop())
            # `_entregar` bloquea esperando al bucle, así que no puede correr en
            # él: es exactamente la situación real, donde lo llama uvicorn desde
            # su propio hilo.
            return await asyncio.to_thread(
                avisos_http._entregar, {"app": "Claude Code", "titulo": "", "cuerpo": "ok"}
            )

        self.assertTrue(asyncio.run(escenario()))
        self.assertIn('"tipo": "aviso"', conexion.enviados[0])

    def test_si_la_conexion_falla_se_dice_que_no_llego(self):
        class _Rota:
            async def send(self, _crudo):
                raise RuntimeError("conexión caída")

        async def escenario():
            avisos_http.registrar(_Rota(), asyncio.get_running_loop())
            return await asyncio.to_thread(
                avisos_http._entregar, {"app": "", "titulo": "x", "cuerpo": ""}
            )

        self.assertFalse(asyncio.run(escenario()))

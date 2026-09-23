"""La voz sale del Mac, y si no está, de la nube: nunca se queda muda."""
import asyncio
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.executors import local_speech
from app.executors.edge_speech import SintesisError
from tests.test_nodes import NodeTestCase


class ElEndpointEligeLaVoz(NodeTestCase):
    def setUp(self):
        super().setUp()
        token = self.registrar(nodo="Sobremesa").json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    def pedir(self, texto="Vale."):
        return self.client.post("/api/tts", headers=self.headers, json={"texto": texto})

    def test_con_la_voz_local_devuelve_su_wav(self):
        with patch.object(settings, "tts_engine", "local"), patch(
            "app.api.local_speech.sintetizar", AsyncMock(return_value=b"RIFFwav")
        ), patch("app.api.edge_speech.sintetizar", AsyncMock()) as nube:
            respuesta = self.pedir()

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.headers["content-type"], "audio/wav")
        self.assertEqual(respuesta.content, b"RIFFwav")
        nube.assert_not_awaited()

    def test_sin_voz_local_cae_a_la_nube(self):
        with patch.object(settings, "tts_engine", "local"), patch(
            "app.api.local_speech.sintetizar",
            AsyncMock(side_effect=SintesisError("no responde")),
        ), patch(
            "app.api.edge_speech.sintetizar", AsyncMock(return_value=b"ID3mp3")
        ):
            respuesta = self.pedir()

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.headers["content-type"], "audio/mpeg")
        self.assertEqual(respuesta.content, b"ID3mp3")

    def test_con_edge_elegido_no_se_pregunta_a_la_local(self):
        with patch.object(settings, "tts_engine", "edge"), patch(
            "app.api.local_speech.sintetizar", AsyncMock()
        ) as local, patch(
            "app.api.edge_speech.sintetizar", AsyncMock(return_value=b"ID3mp3")
        ):
            respuesta = self.pedir()

        self.assertEqual(respuesta.headers["content-type"], "audio/mpeg")
        local.assert_not_awaited()

    def test_si_fallan_las_dos_es_un_502(self):
        with patch.object(settings, "tts_engine", "local"), patch(
            "app.api.local_speech.sintetizar", AsyncMock(side_effect=SintesisError("x"))
        ), patch(
            "app.api.edge_speech.sintetizar", AsyncMock(side_effect=SintesisError("y"))
        ):
            respuesta = self.pedir()

        self.assertEqual(respuesta.status_code, 502)

    def test_exige_autenticacion(self):
        self.assertEqual(self.client.post("/api/tts", json={"texto": "hola"}).status_code, 401)


class _ServicioFalso(BaseHTTPRequestHandler):
    """Hace de `voz_local/servidor.py`: apunta lo que le piden."""

    pedidos: list = []
    estado = 200

    def log_message(self, *_):
        pass

    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).pedidos.append((self.path, cuerpo))
        datos = b"RIFFwav" if type(self).estado == 200 else b'{"error":"mal"}'
        self.send_response(type(self).estado)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)


class ElClienteDeLaVozLocal(unittest.TestCase):
    def setUp(self):
        _ServicioFalso.pedidos, _ServicioFalso.estado = [], 200
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), _ServicioFalso)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.shutdown)
        url = f"http://127.0.0.1:{self.http.server_address[1]}"
        for nombre, valor in (("tts_local_url", url), ("tts_local_voice", "em_santa"),
                              ("tts_local_speed", 1.1)):
            parche = patch.object(settings, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)

    def test_pide_el_texto_con_la_voz_y_la_velocidad_configuradas(self):
        audio = asyncio.run(local_speech.sintetizar("  Hola.  "))

        self.assertEqual(audio, b"RIFFwav")
        self.assertEqual(
            _ServicioFalso.pedidos,
            [("/tts", {"texto": "Hola.", "velocidad": 1.1, "voz": "em_santa"})],
        )

    def test_un_error_del_servicio_es_un_fallo_de_sintesis(self):
        _ServicioFalso.estado = 500

        with self.assertRaises(SintesisError):
            asyncio.run(local_speech.sintetizar("Hola."))

    def test_si_no_hay_nadie_escuchando_falla_enseguida(self):
        self.http.shutdown()
        self.http.server_close()

        with self.assertRaises(SintesisError):
            asyncio.run(local_speech.sintetizar("Hola."))

    def test_sin_texto_no_se_llama(self):
        with self.assertRaises(SintesisError):
            asyncio.run(local_speech.sintetizar("   "))
        self.assertEqual(_ServicioFalso.pedidos, [])

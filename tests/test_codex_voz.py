"""La voz de Codex habla, pero el trabajo lo sigue haciendo Vibi."""
import json
import sys
import tempfile
import textwrap
import threading
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from app import db
from app.core.messages import ResultadoMensaje
from app.executors import codex_voz
from tests.test_nodes import NodeTestCase

# Un app-server de mentira: contesta lo justo para negociar la llamada y luego
# pide la herramienta de Vibi, como haría Codex al oír una petición.
FALSO_APP_SERVER = textwrap.dedent(
    """
    import json, sys
    def enviar(mensaje):
        sys.stdout.write(json.dumps(mensaje) + "\\n"); sys.stdout.flush()
    for linea in sys.stdin:
        mensaje = json.loads(linea)
        metodo, ident = mensaje.get("method"), mensaje.get("id")
        if metodo == "initialize":
            enviar({"id": ident, "result": {}})
        elif metodo == "account/read":
            enviar({"id": ident, "result": {"account": {"type": "CUENTA"}}})
        elif metodo == "thread/start":
            assert [h["name"] for h in mensaje["params"]["dynamicTools"]] == [
                "vibi_request", "terminar_conversacion"]
            enviar({"id": ident, "result": {"thread": {"id": "hilo"}}})
        elif metodo == "thread/realtime/start":
            assert mensaje["params"]["voice"] == "maple"
            enviar({"id": ident, "result": {}})
            enviar({"method": "thread/realtime/sdp", "params": {"sdp": "v=0 respuesta"}})
            enviar({"id": 900, "method": "item/tool/call", "params": {
                "tool": "vibi_request", "callId": "c1",
                "arguments": {"request": "apaga la luz"}}})
        elif ident == 900:
            sys.stderr.write(json.dumps(mensaje))
    """
)


def _falso_codex(carpeta: Path, cuenta: str = "chatgpt") -> str:
    guion = carpeta / "app_server.py"
    guion.write_text(FALSO_APP_SERVER.replace("CUENTA", cuenta))
    binario = carpeta / "codex"
    binario.write_text(f"#!/bin/sh\nexec {sys.executable} {guion}\n")
    binario.chmod(0o755)
    return str(binario)


class SesionContraElAppServer(TestCase):
    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())

    def tearDown(self):
        codex_voz.cerrar_todas()

    def test_negocia_la_llamada_y_delega_las_peticiones_en_vibi(self):
        delegado = threading.Event()
        peticiones = []

        def delegar(texto, call_id):
            peticiones.append((texto, call_id))
            delegado.set()
            return {"respuesta": "Hecho."}

        with patch.dict("os.environ", {"VIBI_CODEX_BIN": _falso_codex(self.carpeta)}):
            sdp = codex_voz.abrir("u1", "conv", "v=0 oferta", "maple", delegar)

        self.assertEqual(sdp, "v=0 respuesta")
        self.assertTrue(delegado.wait(5))
        self.assertEqual(peticiones, [("apaga la luz", "c1")])
        activa, eventos = codex_voz.eventos("u1", "conv")
        self.assertTrue(activa)
        self.assertIn({"type": "vibi/request", "text": "apaga la luz"}, eventos)

    def test_sin_sesion_de_chatgpt_no_hay_voz_de_codex(self):
        with patch.dict("os.environ", {"VIBI_CODEX_BIN": _falso_codex(self.carpeta, "apiKey")}):
            with self.assertRaises(codex_voz.CodexNoDisponible):
                codex_voz.abrir("u1", "conv", "v=0 oferta", "maple", lambda *_: {})
        self.assertEqual(codex_voz.eventos("u1", "conv"), (False, []))

    def test_sin_codex_instalado_tampoco(self):
        with patch.object(codex_voz, "ejecutable", return_value=None):
            with self.assertRaises(codex_voz.CodexNoDisponible):
                codex_voz.abrir("u1", "conv", "v=0 oferta", "maple", lambda *_: {})

    def test_tras_agotar_el_limite_de_voz_no_se_reintenta_durante_un_rato(self):
        with patch.object(codex_voz, "_limite_hasta", 0.0):
            codex_voz._marcar_limite()
            with self.assertRaises(codex_voz.CodexNoDisponible):
                codex_voz.abrir("u1", "conv", "v=0 oferta", "maple", lambda *_: {})

    def test_una_voz_desconocida_se_rechaza(self):
        with self.assertRaises(ValueError):
            codex_voz.abrir("u1", "conv", "v=0 oferta", "alloy", lambda *_: {})


class HerramientasDeLaVoz(TestCase):
    def _sesion(self, delegar=lambda *_: {"respuesta": "ok"}):
        sesion = codex_voz.SesionVoz.__new__(codex_voz.SesionVoz)
        sesion.delegar = delegar
        sesion.eventos = []
        sesion.lock = threading.RLock()
        sesion.parando = threading.Event()
        return sesion

    def test_la_despedida_pide_cerrar_la_cara(self):
        sesion = self._sesion()
        resultado = sesion._atender({"tool": "terminar_conversacion", "arguments": {}}, "c")
        self.assertTrue(resultado["success"])
        self.assertEqual(sesion.eventos, [{"type": "vibi/cerrar"}])

    def test_otras_herramientas_no_se_ejecutan(self):
        sesion = self._sesion(delegar=lambda *_: self.fail("no debía delegar"))
        resultado = sesion._atender({"tool": "shell", "arguments": {"request": "rm"}}, "c")
        self.assertFalse(resultado["success"])

    def test_un_fallo_de_vibi_se_le_cuenta_a_codex(self):
        def delegar(*_):
            raise RuntimeError("motor caído")

        sesion = self._sesion(delegar)
        resultado = sesion._atender({"tool": "vibi_request", "arguments": {"request": "x"}}, "c")
        self.assertFalse(resultado["success"])
        self.assertIn("motor caído", json.loads(resultado["contentItems"][0]["text"])["error"])


class EndpointsDeVozCodex(NodeTestCase):
    def setUp(self):
        super().setUp()
        token = self.registrar(nodo="Sobremesa").json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.conversation_id = db.get_or_create_active_conversation(self.user["id"])["id"]

    def _abrir(self, **cambios):
        cuerpo = {"conversation_id": self.conversation_id, "sdp": "v=0 oferta", **cambios}
        return self.client.post("/api/voz/codex", headers=self.headers, json=cuerpo)

    def test_sin_codex_la_cara_sabe_que_debe_usar_la_voz_de_siempre(self):
        with patch.object(codex_voz, "ejecutable", return_value=None):
            response = self._abrir()
        self.assertEqual(response.status_code, 503)

    def test_una_conversacion_ya_cerrada_no_abre_llamada(self):
        response = self._abrir(conversation_id="otra")
        self.assertEqual(response.status_code, 409)

    def test_lo_que_pide_la_voz_entra_en_la_conversacion_de_la_cara(self):
        procesar = AsyncMock(return_value=ResultadoMensaje("rapida", respuesta="Son las 5."))
        devuelto = {}

        def abrir(usuario, conversation_id, sdp, voz, delegar):
            devuelto.update(delegar("¿qué hora es?", "c9"))
            return "v=0 respuesta"

        with patch.object(codex_voz, "abrir", abrir), patch(
            "app.api.message_core.procesar_mensaje", procesar
        ):
            response = self._abrir()

        self.assertEqual(response.json(), {"sdp": "v=0 respuesta", "voz": "maple"})
        self.assertEqual(devuelto, {"respuesta": "Son las 5."})
        _, kwargs = procesar.call_args
        self.assertEqual(kwargs["conversation_id"], self.conversation_id)
        self.assertEqual(kwargs["canal"], "cara")
        self.assertEqual(kwargs["client_ref"], "codex-c9")

    def test_eventos_sin_llamada(self):
        response = self.client.get(
            "/api/voz/codex/eventos",
            headers=self.headers,
            params={"conversation_id": self.conversation_id},
        )
        self.assertEqual(response.json(), {"activa": False, "eventos": []})

    def test_cerrar_la_conversacion_cuelga_la_llamada(self):
        with patch.object(codex_voz, "cerrar") as cerrar:
            self.client.post(
                "/api/voz/cerrar",
                headers=self.headers,
                json={"conversation_id": self.conversation_id},
            )
        cerrar.assert_called_once_with(self.user["id"], self.conversation_id)

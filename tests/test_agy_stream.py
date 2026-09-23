"""`agy` por stream-json: de sus eventos a lo que ya entendía el motor.

Sin lanzar `agy`. Los eventos son los que emite la 1.2.9 de verdad, copiados de
una sesión real el 23/09/2026.
"""
from __future__ import annotations

import json
import queue
import sys
import time
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.executors import agy_client, agy_stream  # noqa: E402


def paso(indice, tipo, estado, **extra):
    return {"event": "step_update", "step_update": {
        "conversation_id": "c1", "step_index": indice, "state": estado,
        "step_type": tipo, **extra,
    }}


RESULTADO = {"event": "result", "result": {
    "conversation_id": "c1", "status": "SUCCESS", "response": "hola\n",
}}


class Mensaje(TestCase):
    def test_es_una_linea_con_el_formato_que_pide_agy(self):
        linea = agy_stream.mensaje("¿qué tal?")

        self.assertTrue(linea.endswith("\n"))
        self.assertEqual(
            json.loads(linea),
            {"event": "user", "message": {"content": "¿qué tal?"}},
        )


class Traducir(TestCase):
    def test_el_texto_llega_acumulado(self):
        t = agy_stream.Traductor()
        t.paso(paso(1, "agent_response", "ACTIVE", text_delta="ho")["step_update"])
        update = t.paso(paso(1, "agent_response", "ACTIVE", text_delta="la")["step_update"])

        self.assertEqual(update.text, "hola")

    def test_dos_bloques_separados_por_una_herramienta_no_se_pegan(self):
        t = agy_stream.Traductor()
        t.paso(paso(1, "agent_response", "DONE", text_delta="Lo miro.")["step_update"])
        t.paso(paso(2, "tool", "DONE", tool_name="view_file")["step_update"])
        update = t.paso(paso(3, "agent_response", "ACTIVE", text_delta="Pone hola.")["step_update"])

        self.assertEqual(update.text, "Lo miro.\n\nPone hola.")

    def test_una_herramienta_activa_cuenta_como_en_curso(self):
        t = agy_stream.Traductor()
        update = t.paso(paso(2, "tool", "ACTIVE", tool_name="run_command", tool_info={
            "name": "run_command", "parameters": {"CommandLine": "ls -la"},
        })["step_update"])

        self.assertTrue(update.tools_running)
        self.assertEqual(update.pasos[0].tipo, agy_client.STEP_RUN_COMMAND)
        self.assertEqual(update.pasos[0].detalle, "ls -la")

    def test_al_acabar_deja_de_estar_en_curso(self):
        t = agy_stream.Traductor()
        t.paso(paso(2, "tool", "ACTIVE", tool_name="search_web")["step_update"])
        update = t.paso(paso(2, "tool", "DONE", tool_name="search_web")["step_update"])

        self.assertFalse(update.tools_running)

    def test_el_servidor_mcp_va_delante_del_nombre(self):
        paso = {"tool_name": "call_mcp_tool", "tool_info": {
            "name": "call_mcp_tool",
            "parameters": {"Arguments": {}, "ServerName": "vibi", "ToolName": "devices_ui_jev"},
        }}

        self.assertEqual(agy_stream.tipo_de_herramienta(paso), "mcp__vibi__devices_ui_jev")
        self.assertEqual(agy_stream.detalle_de_herramienta(paso), "vibi: devices_ui_jev")


class ProcesoFalso:
    def __init__(self, eventos):
        self._eventos = queue.Queue()
        for evento in eventos:
            self._eventos.put(evento)
        self.conversation_id = "c1"
        self.conocidas = ["c1"]
        self.entradas = 0
        self.muerto = False
        self._reservada = True

    def kill(self, conservar_log=False):
        self.muerto = True

    def cortar(self):
        self.muerto = True


class Cliente(TestCase):
    def cliente(self, *eventos):
        proceso = ProcesoFalso([])
        cliente = agy_stream.AgyStreamClient(proceso)
        stream = cliente.stream_updates("c1", timeout=2)
        for evento in eventos:
            proceso._eventos.put(evento)
        return cliente, stream

    def test_el_turno_termina_con_el_result(self):
        _, stream = self.cliente(
            paso(0, "user_input", "DONE"),
            paso(1, "agent_response", "ACTIVE", text_delta="hola"),
            RESULTADO,
            paso(5, "agent_response", "ACTIVE", text_delta="esto ya es de otro turno"),
        )

        updates = list(stream)

        self.assertEqual(updates[-1].text, "hola")
        self.assertTrue(updates[-1].done)
        self.assertFalse(updates[-1].trabajando)

    def test_lo_que_sobraba_de_antes_no_entra_en_este_turno(self):
        proceso = ProcesoFalso([paso(9, "agent_response", "DONE", text_delta="viejo")])
        stream = agy_stream.AgyStreamClient(proceso).stream_updates("c1", timeout=2)
        proceso._eventos.put(paso(1, "agent_response", "ACTIVE", text_delta="nuevo"))
        proceso._eventos.put(RESULTADO)

        self.assertEqual(list(stream)[-1].text, "nuevo")

    def test_un_error_sin_respuesta_es_un_fallo(self):
        _, stream = self.cliente({"event": "result", "result": {
            "status": "ERROR", "error": "cuota agotada", "response": "",
        }})

        with self.assertRaises(agy_client.AgyError):
            list(stream)

    def test_si_agy_se_cierra_a_medias_es_un_fallo(self):
        _, stream = self.cliente(paso(0, "user_input", "DONE"), agy_stream._FIN)

        with self.assertRaises(agy_client.AgyError):
            list(stream)

    def test_otra_conversacion_no_se_escucha(self):
        cliente = agy_stream.AgyStreamClient(ProcesoFalso([]))

        with self.assertRaises(agy_client.AgyError):
            cliente.stream_updates("otra")

    def test_parar_mata_el_proceso(self):
        proceso = ProcesoFalso([])

        agy_stream.AgyStreamClient(proceso).stop("c1")

        self.assertTrue(proceso.muerto)

    def test_cuenta_las_entradas_solo_de_su_conversacion(self):
        proceso = ProcesoFalso([])
        proceso.entradas = 3
        cliente = agy_stream.AgyStreamClient(proceso)

        self.assertEqual(cliente.user_input_count("c1"), 3)
        self.assertEqual(cliente.user_input_count("otra"), 0)


class Comando(TestCase):
    def test_modo_stream_json_sin_terminal(self):
        proceso = agy_stream.AgyStreamProcess("/opt/homebrew/bin/agy", "/tmp/w", "gemini-3.6-flash-low", "low")
        comando = proceso._comando()

        self.assertIn("stream-json", comando)
        self.assertEqual(comando[-1], "--print=")
        # El esfuerzo ya va en el nombre del modelo: repetirlo lo rechaza.
        self.assertNotIn("--effort", comando)


class ConversacionNueva(TestCase):
    def test_un_proceso_sin_estrenar_sirve_como_conversacion_nueva(self):
        proceso = agy_stream.AgyStreamProcess("agy", "/tmp/w")
        proceso.conversation_id, proceso.conocidas = "c1", ["c1"]
        proceso.alive = lambda: True
        cliente = proceso.cliente()
        antes = set(cliente.conversations())

        proceso.type("/new")

        self.assertEqual(set(cliente.conversations()) - antes, {"c1"})


class PopenFalso:
    def __init__(self):
        self.vivo = True
        self.stdin = None

    def poll(self):
        return None if self.vivo else 0

    def terminate(self):
        self.vivo = False

    def wait(self, timeout=None):
        return 0


def conexion(cid):
    c = agy_stream._Conexion(PopenFalso(), agy_stream._nuevo_log())
    c.conversation_id = cid
    return c


class Repuesto(TestCase):
    """Una conversación nueva no espera a que arranque su `agy`: ya lo estaba."""

    def proceso(self, lanzadas):
        proceso = agy_stream.AgyStreamProcess("agy", "/tmp/w")
        cola = iter(lanzadas)
        proceso._lanzar = lambda _timeout: next(cola)
        proceso._estrenar(proceso._lanzar(1))
        proceso._preparar_repuesto()
        proceso._preparando.join(2)
        return proceso

    def test_al_arrancar_deja_otro_esperando(self):
        proceso = self.proceso([conexion("c1"), conexion("c2")])

        self.assertEqual(proceso.conversation_id, "c1")
        self.assertEqual(proceso._repuesto.conversation_id, "c2")

    def test_new_pasa_al_repuesto_sin_lanzar_nada_en_el_turno(self):
        proceso = self.proceso([conexion("c1"), conexion("c2"), conexion("c3")])
        vieja = proceso._actual
        proceso.entradas = 1  # ya estrenada: `/new` tiene que cambiar de agy
        lanzados_en_el_turno = []
        original = proceso._lanzar
        proceso._lanzar = lambda t: lanzados_en_el_turno.append(1) or original(t)

        proceso.type("/new")

        self.assertEqual(proceso.conversation_id, "c2")
        self.assertIn("c2", proceso.cliente().conversations())
        # Lo que se lanza es el repuesto siguiente, en segundo plano.
        proceso._preparando.join(2)
        self.assertEqual(proceso._repuesto.conversation_id, "c3")
        for _ in range(50):
            if not vieja.viva():
                break
            time.sleep(0.02)
        self.assertFalse(vieja.viva())

    def test_sin_repuesto_arranca_uno_como_antes(self):
        proceso = agy_stream.AgyStreamProcess("agy", "/tmp/w", repuesto=False)
        cola = iter([conexion("c1"), conexion("c2")])
        proceso._lanzar = lambda _timeout: next(cola)
        proceso._estrenar(proceso._lanzar(1))
        proceso._preparar_repuesto()
        proceso.entradas = 1

        proceso.type("/new")

        self.assertEqual(proceso.conversation_id, "c2")
        self.assertIsNone(proceso._repuesto)

    def test_cortar_deja_atendiendo_al_repuesto(self):
        proceso = self.proceso([conexion("c1"), conexion("c2"), conexion("c3")])
        vieja = proceso._actual

        proceso.cortar()

        self.assertFalse(vieja.viva())
        self.assertTrue(proceso.healthy())
        self.assertEqual(proceso.conversation_id, "c2")
        # Sin estrenar: el `/new` del turno siguiente no lanza nada.
        proceso.type("/new")
        self.assertEqual(proceso.conversation_id, "c2")

    def test_cortar_sin_repuesto_lo_deja_muerto(self):
        proceso = agy_stream.AgyStreamProcess("agy", "/tmp/w", repuesto=False)
        proceso._estrenar(conexion("c1"))

        proceso.cortar()

        self.assertFalse(proceso.alive())

    def test_matarlo_se_lleva_tambien_el_repuesto(self):
        proceso = self.proceso([conexion("c1"), conexion("c2")])
        repuesto = proceso._repuesto

        proceso.kill()

        self.assertFalse(proceso.alive())
        self.assertFalse(repuesto.viva())

    def test_un_repuesto_que_llega_despues_de_cerrar_no_se_queda_vivo(self):
        proceso = agy_stream.AgyStreamProcess("agy", "/tmp/w")
        proceso._estrenar(conexion("c1"))
        tarde = conexion("c2")
        proceso.kill()
        proceso._lanzar = lambda _timeout: tarde

        proceso._arrancar_repuesto()

        self.assertIsNone(proceso._repuesto)
        self.assertFalse(tarde.viva())

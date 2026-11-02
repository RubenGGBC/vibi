"""El móvil es un nodo más, pero nadie le manda nada sin nombrarlo."""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from app import db, movil, nodes, taint, tools
from app.executors import codex_voz
from tests.test_nodes import NodeTestCase

CAPACIDADES = [
    "movil.media",
    "movil.media.reproducir",
    "movil.volumen",
    "movil.notificaciones.listar",
    "movil.notificaciones.descartar",
    "movil.notificaciones.pulsar",
    "movil.notificaciones.responder",
    "movil.apps.abrir",
    "movil.pantalla.leer",
    "movil.pantalla.actuar",
]


class MovilTestCase(NodeTestCase):
    def alta(self, nombre: str, capacidades: list[str]) -> dict:
        token = self.registrar(nodo=nombre).json()["token"]
        node_id = token.split(".")[0]
        db.touch_node(node_id, capacidades)
        return db.get_node(node_id)


class CapacidadesDelMovil(MovilTestCase):
    def test_nodo_movil_declara_capacidades(self):
        self.assertEqual(nodes._sane_capabilities(CAPACIDADES), CAPACIDADES)
        self.assertEqual(list(nodes.CAPACIDADES_MOVIL), CAPACIDADES)

    def test_es_movil_distingue_por_lo_que_declara(self):
        self.assertTrue(nodes.es_movil(self.alta("Galaxy", CAPACIDADES)))
        self.assertFalse(nodes.es_movil(self.alta("PC", ["shell.run"])))

    def test_resolve_device_ignora_el_movil(self):
        pc = self.alta("PC", ["shell.run"])
        self.alta("Galaxy", CAPACIDADES)
        with patch.object(nodes.manager, "is_online", return_value=True):
            self.assertEqual(tools.resolve_device(self.user, None)["id"], pc["id"])

    def test_resolve_device_solo_movil(self):
        self.alta("Galaxy", CAPACIDADES)
        with self.assertRaises(tools.ToolNotFound):
            tools.resolve_device(self.user, None)

    def test_resolve_device_lo_encuentra_si_se_nombra(self):
        movil_node = self.alta("Galaxy", CAPACIDADES)
        self.assertEqual(tools.resolve_device(self.user, "Galaxy")["id"], movil_node["id"])

    def test_lectura_marca_taint(self):
        self.assertIn("devices.movil.notificaciones.listar", taint.FUENTES_EXTERNAS)
        self.assertIn("devices.movil.pantalla.leer", taint.FUENTES_EXTERNAS)


class EjecutarEnElMovil(MovilTestCase):
    def _ejecutar(self, herramienta, argumentos):
        return asyncio.run(movil.ejecutar(self.user, herramienta, argumentos))

    def test_movil_ejecutar_sin_cola(self):
        node = self.alta("Galaxy", CAPACIDADES)
        resultado = self._ejecutar("movil_musica", {"accion": "pausar"})
        self.assertIn("error", resultado)
        self.assertEqual(db.claim_node_orders(node["id"]), [])

    def test_sin_movil_lo_dice(self):
        resultado = self._ejecutar("movil_musica", {"accion": "pausar"})
        self.assertIn("móvil", resultado["error"])

    def test_movil_ejecutar_mapea_capacidad(self):
        casos = [
            ("movil_musica", {"accion": "pausar"}, "movil.media"),
            ("movil_musica", {"accion": "reproducir", "consulta": "x"}, "movil.media.reproducir"),
            ("movil_volumen", {"accion": "subir"}, "movil.volumen"),
            ("movil_notificaciones", {"accion": "listar"}, "movil.notificaciones.listar"),
            ("movil_notificaciones", {"accion": "descartar", "id": "1"}, "movil.notificaciones.descartar"),
            ("movil_notificaciones", {"accion": "pulsar", "id": "1", "boton": "b"}, "movil.notificaciones.pulsar"),
            ("movil_notificaciones", {"accion": "responder", "id": "1", "texto": "t"}, "movil.notificaciones.responder"),
            ("movil_abrir", {"destino": "Ajustes"}, "movil.apps.abrir"),
            ("movil_pantalla", {"accion": "leer"}, "movil.pantalla.leer"),
            ("movil_pantalla", {"accion": "tocar", "objetivo": "3"}, "movil.pantalla.actuar"),
        ]
        for herramienta, argumentos, esperada in casos:
            self.assertEqual(movil.capacidad_para(herramienta, argumentos), esperada)

    def test_accion_desconocida_devuelve_error(self):
        self.alta("Galaxy", CAPACIDADES)
        self.assertIn("error", self._ejecutar("movil_musica", {"accion": "explotar"}))
        self.assertIn("error", self._ejecutar("movil_shell", {"accion": "x"}))

    def test_resultado_y_error_del_movil_llegan_a_la_voz(self):
        self.alta("Galaxy", CAPACIDADES)
        correcto = {"estado": "ok", "resultado": {"sonando": "Eye of the Tiger"}}
        with patch.object(nodes, "dispatch", AsyncMock(return_value=correcto)) as dispatch:
            resultado = self._ejecutar("movil_musica", {"accion": "que_suena"})
        self.assertEqual(resultado, {"sonando": "Eye of the Tiger"})
        self.assertFalse(dispatch.call_args.kwargs["queue_if_offline"])
        fallido = {"estado": "error", "resultado": {"codigo": "sin_musica", "error": "No suena nada"}}
        with patch.object(nodes, "dispatch", AsyncMock(return_value=fallido)):
            resultado = self._ejecutar("movil_musica", {"accion": "pausar"})
        self.assertEqual(resultado, {"codigo": "sin_musica", "error": "No suena nada"})

    def test_timeout_no_cuenta_como_exito(self):
        self.alta("Galaxy", CAPACIDADES)
        with patch.object(nodes, "dispatch", AsyncMock(return_value={"estado": "timeout"})):
            self.assertIn("error", self._ejecutar("movil_musica", {"accion": "pausar"}))


class SesionConMovil(TestCase):
    def _sesion(self, delegar, delegar_movil=None):
        sesion = codex_voz.SesionVoz.__new__(codex_voz.SesionVoz)
        sesion.delegar = delegar
        sesion.delegar_movil = delegar_movil
        sesion.eventos = []
        sesion.lock = threading.RLock()
        sesion.parando = threading.Event()
        sesion.resultados = {}
        sesion.en_curso = {}
        sesion.lock_herramientas = threading.Lock()
        sesion.escrito = []
        sesion._escribir = sesion.escrito.append
        return sesion

    def test_sin_movil_no_declara_herramientas(self):
        sesion = self._sesion(lambda *_: {})
        nombres = [h["name"] for h in sesion._herramientas()]
        self.assertEqual(nombres, ["vibi_request", "terminar_conversacion"])
        self.assertNotIn("movil_", sesion._instrucciones())

    def test_con_movil_declara_herramientas(self):
        sesion = self._sesion(lambda *_: {}, lambda *_: {})
        nombres = [h["name"] for h in sesion._herramientas()]
        self.assertIn("movil_musica", nombres)
        self.assertIn("movil_pantalla", nombres)
        self.assertIn("movil_", sesion._instrucciones())

    def test_sin_movil_la_herramienta_no_se_ejecuta(self):
        sesion = self._sesion(lambda *_: {})
        resultado = sesion._atender({"tool": "movil_musica", "arguments": {"accion": "pausar"}}, "c")
        self.assertFalse(resultado["success"])

    def test_error_del_movil_no_cuenta_como_exito(self):
        sesion = self._sesion(lambda *_: {}, lambda *_: {"error": "No suena nada"})
        resultado = sesion._atender({"tool": "movil_musica", "arguments": {"accion": "pausar"}}, "c")
        self.assertFalse(resultado["success"])

    def test_herramienta_lenta_no_bloquea(self):
        soltar = threading.Event()

        def lenta(*_):
            soltar.wait(5)
            return {"respuesta": "ya"}

        sesion = self._sesion(lenta, lambda *_: {"ok": True})
        pc = threading.Thread(target=sesion._herramienta, args=({"id": 1, "params": {
            "tool": "vibi_request", "callId": "pc", "arguments": {"request": "compila"}}},))
        pc.start()
        time.sleep(0.1)
        hilo_movil = threading.Thread(target=sesion._herramienta, args=({"id": 2, "params": {
            "tool": "movil_musica", "callId": "m", "arguments": {"accion": "siguiente"}}},))
        hilo_movil.start()
        hilo_movil.join(2)
        terminado = not hilo_movil.is_alive()
        soltar.set()
        pc.join(5)
        hilo_movil.join(5)
        self.assertTrue(terminado)

    def test_callid_repetido_ejecuta_una_vez(self):
        llamadas = []
        soltar = threading.Event()

        def lenta(*_):
            llamadas.append(1)
            soltar.wait(5)
            return {"respuesta": "ya"}

        sesion = self._sesion(lenta)

        def mensaje(identificador):
            return {"id": identificador, "params": {
                "tool": "vibi_request", "callId": "r", "arguments": {"request": "x"}}}

        hilos = [threading.Thread(target=sesion._herramienta, args=(mensaje(i),)) for i in (1, 2)]
        for hilo in hilos:
            hilo.start()
        time.sleep(0.2)
        soltar.set()
        for hilo in hilos:
            hilo.join(5)
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(sorted(m["id"] for m in sesion.escrito), [1, 2])


class LlamadaDesdeElMovil(MovilTestCase):
    def setUp(self):
        super().setUp()
        self.node = self.alta("Galaxy", CAPACIDADES)
        self.addCleanup(codex_voz.cerrar_todas)

    def _token(self):
        return {"Authorization": "Bearer " + self.registrar(nodo="Galaxy 2").json()["token"]}

    def _llamar(self, headers):
        return self.client.post("/api/voz/movil/llamada", headers=headers, json={"sdp": "v=0 oferta"})

    def test_llamada_movil_continua_conversacion(self):
        activa = db.get_or_create_active_conversation(self.user["id"])
        with patch.object(codex_voz, "abrir", return_value="v=0 respuesta") as abrir:
            cuerpo = self._llamar(self._token()).json()
        self.assertEqual(
            cuerpo, {"sdp": "v=0 respuesta", "voz": "maple", "conversation_id": activa["id"]}
        )
        self.assertEqual(abrir.call_args.kwargs["origen"], "movil")
        self.assertIsNotNone(abrir.call_args.kwargs["delegar_movil"])

    def test_llamada_movil_sin_hilo_crea_uno(self):
        with patch.object(codex_voz, "abrir", return_value="v=0 respuesta"):
            cuerpo = self._llamar(self._token()).json()
        self.assertEqual(
            cuerpo["conversation_id"], db.get_active_conversation(self.user["id"])["id"]
        )

    def test_sin_codex_la_llamada_del_movil_da_503(self):
        with patch.object(codex_voz, "ejecutable", return_value=None):
            self.assertEqual(self._llamar(self._token()).status_code, 503)

    def test_escritorio_no_sustituye_llamada_movil(self):
        activa = db.get_or_create_active_conversation(self.user["id"])
        headers = self._token()
        cuerpo = {"conversation_id": activa["id"]}
        with patch.object(codex_voz, "llamada_movil_activa", return_value=True):
            abierta = self.client.post("/api/voz/abrir", headers=headers)
            codex = self.client.post(
                "/api/voz/codex", headers=headers, json={**cuerpo, "sdp": "v=0 oferta"}
            )
            cerrada = self.client.post("/api/voz/cerrar", headers=headers, json=cuerpo)
            colgada = self.client.post("/api/voz/codex/cerrar", headers=headers, json=cuerpo)
        self.assertEqual(abierta.status_code, 409)
        self.assertEqual(codex.status_code, 409)
        self.assertFalse(cerrada.json()["cerrada"])
        self.assertEqual(colgada.status_code, 409)
        self.assertEqual(db.get_active_conversation(self.user["id"])["id"], activa["id"])

    def test_colgar_el_movil_no_archiva(self):
        activa = db.get_or_create_active_conversation(self.user["id"])
        with patch.object(codex_voz, "cerrar", return_value=True) as cerrar:
            respuesta = self.client.post("/api/voz/movil/colgar", headers=self._token())
        self.assertEqual(respuesta.status_code, 200)
        cerrar.assert_called_once_with(self.user["id"])
        self.assertEqual(db.get_active_conversation(self.user["id"])["id"], activa["id"])

    def test_llamada_activa_detecta_origen(self):
        sesion = SimpleNamespace(
            origen="movil", cerrada=False, proceso=SimpleNamespace(poll=lambda: None)
        )
        with patch.dict(codex_voz._sesiones, {"u": sesion}):
            self.assertTrue(codex_voz.llamada_movil_activa("u"))
            sesion.origen = "escritorio"
            self.assertFalse(codex_voz.llamada_movil_activa("u"))
        self.assertFalse(codex_voz.llamada_movil_activa("otro"))

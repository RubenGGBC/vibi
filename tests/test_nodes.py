import asyncio
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import auth, db, nodes, tools
from app.config import settings
from app.main import create_app


class NodeTestCase(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.patches = [
            patch.object(settings, "db_path", str(root / "vibi.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
            patch.object(
                settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"
            ),
            patch.object(settings, "node_result_timeout_seconds", 1),
        ]
        for setting_patch in self.patches:
            setting_patch.start()
            self.addCleanup(setting_patch.stop)

        db.init_db()
        self.user = db.get_or_create_user("ruben")
        db.set_password_hash(self.user["id"], auth.hash_password("correcta"))
        self.other = db.get_or_create_user("otra")
        db.set_password_hash(self.other["id"], auth.hash_password("otra-clave"))

        self.client = TestClient(
            create_app(start_background=False, frontend_dir=root / "missing-dist")
        )
        self.addCleanup(self.client.close)
        self.addCleanup(nodes.manager.connections.clear)
        self.token = self.client.post(
            "/api/auth/login",
            json={"nombre": "ruben", "contraseña": "correcta"},
        ).json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def registrar(self, nodo="MacBook Pro", usuario="ruben", clave="correcta"):
        return self.client.post(
            "/api/auth/nodos",
            json={
                "nombre": usuario,
                "contraseña": clave,
                "nodo": nodo,
                "plataforma": "Darwin 24.0",
            },
        )


class AltaDeNodos(NodeTestCase):
    def test_alta_devuelve_token_y_no_filtra_el_hash(self):
        response = self.registrar()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["token"].startswith(body["nodo"]["id"] + "."))
        self.assertNotIn("token_hash", body["nodo"])
        self.assertEqual(body["nodo"]["nombre"], "MacBook Pro")
        self.assertFalse(body["nodo"]["conectado"])

    def test_el_token_se_guarda_hasheado(self):
        token = self.registrar().json()["token"]
        node = db.get_node(token.split(".")[0])
        self.assertNotIn(token.split(".", 1)[1], node["token_hash"])
        self.assertEqual(len(node["token_hash"]), 64)

    def test_alta_rechaza_credenciales_invalidas(self):
        response = self.registrar(clave="incorrecta")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(db.list_nodes(self.user["id"]), [])

    def test_alta_rechaza_nombre_repetido(self):
        self.registrar()
        response = self.registrar()
        self.assertEqual(response.status_code, 409)

    def test_dos_usuarios_pueden_usar_el_mismo_nombre(self):
        self.registrar()
        response = self.registrar(usuario="otra", clave="otra-clave")
        self.assertEqual(response.status_code, 200)


class ListadoYRevocacion(NodeTestCase):
    def test_solo_veo_mis_nodos(self):
        self.registrar()
        self.registrar(nodo="Portátil ajeno", usuario="otra", clave="otra-clave")

        listado = self.client.get("/api/nodos", headers=self.headers).json()
        self.assertEqual([n["nombre"] for n in listado["nodos"]], ["MacBook Pro"])

    def test_no_puedo_revocar_el_nodo_de_otro(self):
        ajeno = self.registrar(
            nodo="Portátil ajeno", usuario="otra", clave="otra-clave"
        ).json()["nodo"]

        response = self.client.post(
            f"/api/nodos/{ajeno['id']}/revocar", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(db.get_node(ajeno["id"])["estado"], "activo")

    def test_revocar_invalida_el_token_y_caduca_lo_pendiente(self):
        alta = self.registrar().json()
        node_id, token = alta["nodo"]["id"], alta["token"]
        db.create_node_order(node_id, self.user["id"], "ping", {}, 3600)

        response = self.client.post(
            f"/api/nodos/{node_id}/revocar", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(nodes.node_from_token(token))
        pendientes = db.list_node_orders(node_id, self.user["id"])
        self.assertEqual([o["estado"] for o in pendientes], ["caducada"])

    def test_el_nombre_se_reutiliza_tras_revocar(self):
        node_id = self.registrar().json()["nodo"]["id"]
        self.client.post(f"/api/nodos/{node_id}/revocar", headers=self.headers)
        self.assertEqual(self.registrar().status_code, 200)


class Tokens(NodeTestCase):
    def test_token_manipulado_no_vale(self):
        alta = self.registrar().json()
        node_id = alta["nodo"]["id"]
        self.assertIsNone(nodes.node_from_token(f"{node_id}.secreto-inventado"))
        self.assertIsNone(nodes.node_from_token("sin-punto"))
        self.assertIsNone(nodes.node_from_token(""))

    def test_token_legitimo_resuelve_el_nodo(self):
        alta = self.registrar().json()
        node = nodes.node_from_token(alta["token"])
        self.assertEqual(node["id"], alta["nodo"]["id"])


class ResolucionPorNombre(NodeTestCase):
    def setUp(self):
        super().setUp()
        self.registrar(nodo="MacBook Pro")
        self.registrar(nodo="PC main")

    def test_resuelve_ignorando_mayusculas(self):
        node = nodes.resolve(self.user["id"], "macbook pro")
        self.assertEqual(node["nombre"], "MacBook Pro")

    def test_resuelve_por_fragmento(self):
        node = nodes.resolve(self.user["id"], "main")
        self.assertEqual(node["nombre"], "PC main")

    def test_nombre_ambiguo_pregunta_en_vez_de_adivinar(self):
        self.registrar(nodo="MacBook Air")
        with self.assertRaises(nodes.NodeAmbiguous):
            nodes.resolve(self.user["id"], "macbook")

    def test_nodo_de_otro_usuario_no_existe_para_mi(self):
        self.registrar(nodo="Torre de otra", usuario="otra", clave="otra-clave")
        with self.assertRaises(nodes.NodeNotFound):
            nodes.resolve(self.user["id"], "Torre de otra")


class ColaDeOrdenes(NodeTestCase):
    def test_orden_a_nodo_apagado_queda_pendiente(self):
        node = self.registrar().json()["nodo"]
        outcome = asyncio.run(
            nodes.dispatch(self.user, db.get_node(node["id"]), "projects.list")
        )
        self.assertEqual(outcome["estado"], "pendiente")
        orden = db.get_node_order(outcome["order_id"])
        self.assertEqual(orden["estado"], "pendiente")

    def test_ping_a_nodo_apagado_no_encola(self):
        node = self.registrar().json()["nodo"]
        with self.assertRaises(nodes.NodeOffline):
            asyncio.run(
                nodes.dispatch(
                    self.user,
                    db.get_node(node["id"]),
                    "ping",
                    queue_if_offline=False,
                )
            )
        self.assertEqual(db.list_node_orders(node["id"], self.user["id"]), [])

    def test_no_encolable_desconectada_antes_del_envio_se_cancela(self):
        node = self.registrar().json()["nodo"]
        with patch.object(
            nodes.manager, "is_online", side_effect=(True, False)
        ):
            outcome = asyncio.run(
                nodes.dispatch(
                    self.user,
                    db.get_node(node["id"]),
                    "ping",
                    queue_if_offline=False,
                )
            )

        self.assertEqual(outcome["estado"], "offline")
        order = db.get_node_order(outcome["order_id"])
        self.assertEqual(order["estado"], "error")
        self.assertEqual(db.claim_node_orders(node["id"]), [])

    def test_no_encolable_con_envio_incierto_no_se_reintenta(self):
        node = self.registrar().json()["nodo"]
        with patch.object(nodes.manager, "is_online", return_value=True), patch.object(
            nodes.manager, "send", AsyncMock(return_value=False)
        ):
            outcome = asyncio.run(
                nodes.dispatch(
                    self.user,
                    db.get_node(node["id"]),
                    "ping",
                    queue_if_offline=False,
                )
            )

        self.assertEqual(outcome["estado"], "timeout")
        order = db.get_node_order(outcome["order_id"])
        self.assertEqual(order["estado"], "error")
        self.assertEqual(db.claim_node_orders(node["id"]), [])

    def test_capacidad_desconocida_se_rechaza_en_el_servidor(self):
        node = self.registrar().json()["nodo"]
        with self.assertRaises(nodes.UnsupportedCapability):
            asyncio.run(
                nodes.dispatch(self.user, db.get_node(node["id"]), "teletransporte")
            )

    def test_las_ordenes_caducan_y_no_reviven(self):
        node = self.registrar().json()["nodo"]
        orden = db.create_node_order(
            node["id"], self.user["id"], "ping", {}, -1
        )
        caducadas = db.expire_node_orders()

        self.assertEqual([o["id"] for o in caducadas], [orden["id"]])
        self.assertEqual(db.get_node_order(orden["id"])["estado"], "caducada")
        self.assertEqual(db.claim_node_orders(node["id"]), [])

    def test_un_nodo_no_puede_cerrar_la_orden_de_otro(self):
        mio = self.registrar().json()["nodo"]
        ajeno = self.registrar(nodo="PC main").json()["nodo"]
        orden = db.create_node_order(mio["id"], self.user["id"], "ping", {}, 3600)

        self.assertIsNone(
            db.finish_node_order(orden["id"], ajeno["id"], "ok", {"pong": True})
        )
        self.assertEqual(db.get_node_order(orden["id"])["estado"], "pendiente")

    def test_una_orden_solo_se_cierra_una_vez(self):
        node = self.registrar().json()["nodo"]
        orden = db.create_node_order(node["id"], self.user["id"], "ping", {}, 3600)

        self.assertIsNotNone(
            db.finish_node_order(orden["id"], node["id"], "ok", {"pong": True})
        )
        self.assertIsNone(
            db.finish_node_order(orden["id"], node["id"], "error", {"error": "no"})
        )
        self.assertEqual(db.get_node_order(orden["id"])["estado"], "ok")


class ConexionDelAgente(NodeTestCase):
    def test_token_invalido_cierra_la_conexion(self):
        with self.client.websocket_connect("/api/nodos/ws") as ws:
            ws.send_json({"tipo": "hola", "token": "no-existe.nada"})
            with self.assertRaises(Exception):
                ws.receive_json()

    def test_conectar_marca_el_nodo_como_disponible(self):
        alta = self.registrar().json()
        with self.client.websocket_connect("/api/nodos/ws") as ws:
            ws.send_json(
                {
                    "tipo": "hola",
                    "token": alta["token"],
                    "capacidades": ["ping", "projects.list"],
                }
            )
            saludo = ws.receive_json()
            self.assertEqual(saludo["tipo"], "conexion_lista")
            self.assertEqual(saludo["nombre"], "MacBook Pro")

            listado = self.client.get("/api/nodos", headers=self.headers).json()
            self.assertTrue(listado["nodos"][0]["conectado"])
            self.assertEqual(
                listado["nodos"][0]["capacidades"], ["ping", "projects.list"]
            )

        self.assertFalse(nodes.manager.is_online(alta["nodo"]["id"]))

    def test_capacidades_inventadas_se_descartan(self):
        alta = self.registrar().json()
        with self.client.websocket_connect("/api/nodos/ws") as ws:
            ws.send_json(
                {
                    "tipo": "hola",
                    "token": alta["token"],
                    "capacidades": ["ping", "teletransporte", 42],
                }
            )
            ws.receive_json()
            node = db.get_node(alta["nodo"]["id"])
            self.assertEqual(node["capacidades"], ["ping"])

    def test_al_conectar_recibe_lo_que_quedo_pendiente(self):
        alta = self.registrar().json()
        orden = db.create_node_order(
            alta["nodo"]["id"], self.user["id"], "projects.list", {}, 3600
        )

        with self.client.websocket_connect("/api/nodos/ws") as ws:
            ws.send_json({"tipo": "hola", "token": alta["token"]})
            ws.receive_json()
            entregada = ws.receive_json()

            self.assertEqual(entregada["tipo"], "orden")
            self.assertEqual(entregada["id"], orden["id"])
            self.assertEqual(entregada["capability"], "projects.list")
            self.assertEqual(
                db.get_node_order(orden["id"])["estado"], "entregada"
            )

    def test_el_resultado_del_agente_cierra_la_orden(self):
        alta = self.registrar().json()
        orden = db.create_node_order(
            alta["nodo"]["id"], self.user["id"], "projects.list", {}, 3600
        )

        with self.client.websocket_connect("/api/nodos/ws") as ws:
            ws.send_json({"tipo": "hola", "token": alta["token"]})
            ws.receive_json()
            ws.receive_json()
            ws.receive_json()  # suscripción completa de vigilancias
            ws.send_json(
                {
                    "tipo": "resultado",
                    "id": orden["id"],
                    "estado": "ok",
                    "resultado": {"proyectos": [{"nombre": "vibi"}]},
                }
            )
            ws.send_json({"tipo": "ping"})
            self.assertEqual(ws.receive_json()["tipo"], "pong")

        cerrada = db.get_node_order(orden["id"])
        self.assertEqual(cerrada["estado"], "ok")
        self.assertEqual(
            cerrada["resultado"], {"proyectos": [{"nombre": "vibi"}]}
        )

    def test_un_resultado_enorme_se_rechaza(self):
        alta = self.registrar().json()
        orden = db.create_node_order(
            alta["nodo"]["id"], self.user["id"], "projects.list", {}, 3600
        )

        with self.client.websocket_connect("/api/nodos/ws") as ws:
            ws.send_json({"tipo": "hola", "token": alta["token"]})
            ws.receive_json()
            ws.receive_json()
            ws.receive_json()  # suscripción completa de vigilancias
            ws.send_json(
                {
                    "tipo": "resultado",
                    "id": orden["id"],
                    "estado": "ok",
                    "resultado": {"relleno": "x" * (nodes.MAX_RESULT_BYTES + 1)},
                }
            )
            ws.send_json({"tipo": "ping"})
            ws.receive_json()

        cerrada = db.get_node_order(orden["id"])
        self.assertEqual(cerrada["estado"], "error")
        self.assertIn("demasiado grande", cerrada["resultado"]["error"])

    def test_conexion_nueva_sustituye_a_la_anterior(self):
        alta = self.registrar().json()
        with self.client.websocket_connect("/api/nodos/ws") as primera:
            primera.send_json({"tipo": "hola", "token": alta["token"]})
            primera.receive_json()
            with self.client.websocket_connect("/api/nodos/ws") as segunda:
                segunda.send_json({"tipo": "hola", "token": alta["token"]})
                segunda.receive_json()
                self.assertTrue(nodes.manager.is_online(alta["nodo"]["id"]))


class PrimitivasDelModelo(NodeTestCase):
    def test_devices_list_solo_muestra_los_mios(self):
        self.registrar()
        self.registrar(nodo="Torre ajena", usuario="otra", clave="otra-clave")

        salida = asyncio.run(tools.execute("devices.list", self.user))["result"]
        self.assertEqual([d["name"] for d in salida["devices"]], ["MacBook Pro"])
        self.assertFalse(salida["devices"][0]["online"])

    def test_devices_ping_responde_apagado_sin_error(self):
        self.registrar()
        salida = asyncio.run(
            tools.execute("devices.ping", self.user, {"device": "macbook"})
        )["result"]
        self.assertFalse(salida["online"])

    def test_devices_ping_con_nombre_desconocido(self):
        with self.assertRaises(tools.ToolNotFound):
            asyncio.run(
                tools.execute("devices.ping", self.user, {"device": "la tostadora"})
            )

    def test_devices_projects_encola_si_esta_apagado(self):
        node = self.registrar().json()["nodo"]
        salida = asyncio.run(
            tools.execute("devices.projects", self.user, {"device": "macbook"})
        )["result"]
        self.assertEqual(salida["state"], "pendiente")
        self.assertIn("pendiente", salida["message"])
        self.assertEqual(
            [o["estado"] for o in db.list_node_orders(node["id"], self.user["id"])],
            ["pendiente"],
        )


class ActividadDeNodos(NodeTestCase):
    def test_el_alta_queda_registrada_en_actividad(self):
        self.registrar()
        actividad = self.client.get(
            "/api/actividad?categoria=dispositivos", headers=self.headers
        ).json()

        tipos = [evento["tipo"] for evento in actividad["eventos"]]
        self.assertIn("nodo_registrado", tipos)
        registro = next(
            e for e in actividad["eventos"] if e["tipo"] == "nodo_registrado"
        )
        self.assertEqual(registro["categoria"], "dispositivos")
        self.assertEqual(registro["detalle"], "MacBook Pro")

    def test_la_actividad_de_nodos_no_se_filtra_entre_usuarios(self):
        ajeno = self.registrar(
            nodo="Torre ajena", usuario="otra", clave="otra-clave"
        ).json()["nodo"]

        actividad = self.client.get(
            "/api/actividad?categoria=dispositivos", headers=self.headers
        ).json()
        self.assertEqual(actividad["eventos"], [])
        self.assertIsNotNone(db.get_node(ajeno["id"]))

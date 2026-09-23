"""Las guías del lado del servidor: quién puede verlas y cuánto duran.

Lo que se prueba es la promesa que hace el módulo —una foto de tu pantalla que
vive en memoria, caduca sola y no la abre nadie más— y que la herramienta no le
enseñe la imagen al modelo, que es de donde sale su coste cero en tokens.
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import auth, db, guias, tools
from app.config import settings
from app.main import create_app


class ElAlmacen(TestCase):
    def setUp(self):
        guias.olvidar_todo()
        self.addCleanup(guias.olvidar_todo)

    def test_publicar_devuelve_por_donde_se_mira(self):
        publicada = guias.publicar("u1", b"jpeg")

        self.assertEqual(
            publicada["imagen_url"], f"/api/guias/{publicada['id']}/imagen"
        )
        self.assertGreater(publicada["caduca_en"], time.time())
        self.assertEqual(guias.obtener(publicada["id"], "u1"), b"jpeg")

    def test_una_guia_sin_imagen_no_se_publica(self):
        with self.assertRaises(ValueError):
            guias.publicar("u1", b"")

    def test_la_guia_de_otro_no_se_abre(self):
        publicada = guias.publicar("u1", b"jpeg")

        with self.assertRaises(PermissionError):
            guias.obtener(publicada["id"], "u2")

    def test_caduca_sola(self):
        publicada = guias.publicar("u1", b"jpeg")

        # El almacén mide con el reloj monotónico, así que envejecer la guía es
        # adelantar ese reloj y no el del sistema.
        with patch.object(
            guias.time, "monotonic", return_value=time.monotonic() + guias.CADUCIDAD + 1
        ):
            with self.assertRaises(KeyError):
                guias.obtener(publicada["id"], "u1")

    def test_no_se_acumulan_sin_tope(self):
        publicadas = [
            guias.publicar("u1", f"jpeg-{n}".encode())
            for n in range(guias.MAXIMO + 5)
        ]

        self.assertEqual(len(guias._guias), guias.MAXIMO)
        # Las que se van son las más viejas; la última siempre está.
        self.assertEqual(
            guias.obtener(publicadas[-1]["id"], "u1"), f"jpeg-{guias.MAXIMO + 4}".encode()
        )
        with self.assertRaises(KeyError):
            guias.obtener(publicadas[0]["id"], "u1")


class LaUrlDeLaImagen(TestCase):
    def setUp(self):
        guias.olvidar_todo()
        self.addCleanup(guias.olvidar_todo)
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        for ajuste in (
            patch.object(settings, "db_path", str(root / "vibi.db")),
            patch.object(settings, "workspace_root", str(root / "workspace")),
            patch.object(
                settings, "jwt_secret", "secreto-de-pruebas-con-mas-de-32-bytes"
            ),
        ):
            ajuste.start()
            self.addCleanup(ajuste.stop)

        db.init_db()
        self.user = db.get_or_create_user("ruben")
        db.set_password_hash(self.user["id"], auth.hash_password("correcta"))
        self.otra = db.get_or_create_user("ana")
        db.set_password_hash(self.otra["id"], auth.hash_password("correcta"))
        self.client = TestClient(
            create_app(start_background=False, frontend_dir=root / "missing-dist")
        )
        self.addCleanup(self.client.close)

    def _token(self, nombre: str) -> dict:
        respuesta = self.client.post(
            "/api/auth/login", json={"nombre": nombre, "contraseña": "correcta"}
        )
        return {"Authorization": f"Bearer {respuesta.json()['token']}"}

    def test_su_dueno_la_ve_y_no_se_cachea(self):
        publicada = guias.publicar(self.user["id"], b"jpeg")

        respuesta = self.client.get(
            publicada["imagen_url"], headers=self._token("ruben")
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.content, b"jpeg")
        self.assertEqual(respuesta.headers["content-type"], "image/jpeg")
        self.assertEqual(respuesta.headers["cache-control"], "no-store")

    def test_sin_token_no_se_ve_la_pantalla_de_nadie(self):
        publicada = guias.publicar(self.user["id"], b"jpeg")

        respuesta = self.client.get(publicada["imagen_url"])

        self.assertEqual(respuesta.status_code, 401)

    def test_otra_persona_del_laboratorio_tampoco(self):
        publicada = guias.publicar(self.user["id"], b"jpeg")

        respuesta = self.client.get(
            publicada["imagen_url"], headers=self._token("ana")
        )

        self.assertEqual(respuesta.status_code, 403)

    def test_una_guia_caducada_ya_no_está(self):
        respuesta = self.client.get(
            "/api/guias/loquesea/imagen", headers=self._token("ruben")
        )

        self.assertEqual(respuesta.status_code, 404)


class LaHerramienta(TestCase):
    """`devices_ui_guide`: lo que le manda al nodo, a la persona y al modelo."""

    def setUp(self):
        guias.olvidar_todo()
        self.addCleanup(guias.olvidar_todo)
        self.usuario = {"id": "u1", "nombre": "ruben"}
        self.pedido: dict = {}
        self.avisado: list[dict] = []

        self.resultado_del_nodo = {
            "ventana": "Ajustes",
            "pantalla": "pantalla 1 (principal)",
            "ancho": 1568,
            "alto": 882,
            "marcas": [
                {
                    "numero": 1, "ref": "e12", "rol": "boton",
                    "nombre": "Idioma", "texto": "aquí",
                    "x": 10, "y": 20, "ancho": 100, "alto": 40,
                    "recortada": False,
                }
            ],
            "fuera": [],
        }

    def _llamar(self, **campos):
        primitiva = tools.PRIMITIVES["devices.ui_guide"]
        args = primitiva.input_model.model_validate(campos)

        async def dispatch(user, node, capability, arguments, **kwargs):
            self.pedido = {
                "capability": capability,
                "arguments": arguments,
                "kwargs": kwargs,
            }
            return {"estado": "ok", "resultado": self.resultado_del_nodo}

        async def recoger(_captura_id):
            return b"jpeg-de-la-pantalla"

        async def guia_lista(user_id, guia):
            self.avisado.append({"user_id": user_id, "guia": guia})

        with patch.object(
            tools, "resolve_device",
            return_value={"id": "n1", "nombre": "sobremesa", "plataforma": "windows",
                          "estado": "conectado", "capacidades": [],
                          "shell_habilitado": 1, "last_seen": 0, "created_at": 0},
        ), patch.object(tools.nodes, "dispatch", dispatch), \
             patch.object(tools.screenshots, "recoger", recoger), \
             patch.object(tools.events, "guia_lista", guia_lista):
            return asyncio.run(primitiva.handler(self.usuario, args))

    def test_le_pide_al_nodo_señalar_y_no_encola_la_orden(self):
        self._llamar(targets=[{"ref": "e12", "texto": "aquí"}], window="Ajustes")

        self.assertEqual(self.pedido["capability"], "ui.guide")
        self.assertEqual(self.pedido["arguments"]["ventana"], "Ajustes")
        self.assertEqual(
            self.pedido["arguments"]["objetivos"], [{"ref": "e12", "texto": "aquí"}]
        )
        self.assertTrue(self.pedido["arguments"]["captura_id"])
        # Una guía que llegara mañana señalaría sobre otra pantalla.
        self.assertFalse(self.pedido["kwargs"]["queue_if_offline"])

    def test_la_imagen_va_a_la_persona_y_no_al_modelo(self):
        salida = self._llamar(targets=[{"ref": "e12"}])

        [aviso] = self.avisado
        self.assertEqual(aviso["user_id"], "u1")
        # A la persona: la URL, el tamaño de la foto y dónde va cada marca.
        self.assertTrue(aviso["guia"]["imagen_url"])
        self.assertEqual(aviso["guia"]["ancho"], 1568)
        self.assertEqual(aviso["guia"]["marcas"][0]["x"], 10)
        # Al modelo: qué número quedó sobre qué, y ni la imagen ni su URL.
        self.assertNotIn("imagen_url", salida["guia"])
        self.assertNotIn("image", salida)
        self.assertEqual(
            salida["guia"]["marcas"], [{"numero": 1, "ref": "e12",
                                        "rol": "boton", "nombre": "Idioma"}]
        )

    def test_la_imagen_publicada_es_la_que_subio_el_nodo(self):
        self._llamar(targets=[{"ref": "e12"}])

        [aviso] = self.avisado
        self.assertEqual(
            guias.obtener(aviso["guia"]["id"], "u1"), b"jpeg-de-la-pantalla"
        )

    def test_lo_que_no_se_pudo_marcar_llega_al_modelo(self):
        self.resultado_del_nodo["fuera"] = ["e13"]

        salida = self._llamar(targets=[{"ref": "e12"}, {"ref": "e13"}])

        self.assertEqual(salida["guia"]["fuera"], ["e13"])

    def test_señalar_es_leer_y_no_ejecutar(self):
        primitiva = tools.PRIMITIVES["devices.ui_guide"]

        self.assertEqual(primitiva.permissions, ("devices:read:self",))
        from app import nodes

        self.assertIn("ui.guide", nodes.CAPACIDADES_LECTURA)
        self.assertNotIn("ui.guide", nodes.CAPACIDADES_ENTRADA)
        # Y en la lista blanca del despachador, que es otra: sin esto la
        # herramienta existe, el nodo sabe hacerlo y la orden se rechaza al
        # salir. Es justo lo que se coló la primera vez, porque las pruebas
        # de arriba sustituyen `dispatch` entero.
        self.assertIn("ui.guide", nodes.CAPABILITIES)

    def test_mas_de_seis_marcas_no_pasan_ni_del_esquema(self):
        primitiva = tools.PRIMITIVES["devices.ui_guide"]

        with self.assertRaises(Exception):
            primitiva.input_model.model_validate(
                {"targets": [{"ref": f"e{n}"} for n in range(7)]}
            )

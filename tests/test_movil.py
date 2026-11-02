"""El móvil es un nodo más, pero nadie le manda nada sin nombrarlo."""
from unittest.mock import patch

from app import db, nodes, taint, tools
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
        movil = self.alta("Galaxy", CAPACIDADES)
        self.assertEqual(tools.resolve_device(self.user, "Galaxy")["id"], movil["id"])

    def test_lectura_marca_taint(self):
        self.assertIn("devices.movil.notificaciones.listar", taint.FUENTES_EXTERNAS)
        self.assertIn("devices.movil.pantalla.leer", taint.FUENTES_EXTERNAS)

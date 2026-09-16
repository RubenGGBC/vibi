import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app import db, equipo, equipo_coordinador
from app.config import settings
from app.equipo_senales import validar


class EquipoTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.patch_db = patch.object(settings, "db_path", str(Path(self.tempdir.name) / "db.sqlite"))
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)
        db.init_db()
        self.ana = db.get_or_create_user("ana")
        self.dani = db.get_or_create_user("dani")
        self.nodo = db.create_node(self.dani["id"], "Portátil Dani", "Darwin", "hash")
        self.grupo = equipo.crear("Entrega", self.ana["id"])
        equipo.anadir_miembro(self.grupo["id"], self.ana["id"], "dani")
        self.tarea = equipo.crear_tarea(
            self.grupo["id"], self.ana["id"], "Cerrar informe", self.dani["id"]
        )

    def proponer(self, senal="avance", parametros=None):
        return equipo.proponer_seguimiento(
            self.grupo["id"], self.tarea["id"], self.ana["id"], self.nodo["id"],
            senal, parametros or {"ruta": "/tmp/informe"}, "Solo metadatos",
        )

    def test_el_miembro_tiene_que_aprobar_y_puede_revocar(self):
        seguimiento = self.proponer()
        self.assertEqual(equipo.suscripcion(self.nodo["id"]), [])
        with self.assertRaises(equipo.EquipoError):
            equipo.decidir_seguimiento(seguimiento["id"], self.ana["id"], True)
        equipo.decidir_seguimiento(seguimiento["id"], self.dani["id"], True)
        self.assertEqual(equipo.suscripcion(self.nodo["id"])[0]["senal"], "avance")
        equipo.revocar_seguimiento(seguimiento["id"], self.dani["id"])
        self.assertEqual(equipo.suscripcion(self.nodo["id"]), [])

    def test_senal_autenticada_actualiza_creencia_y_tarea(self):
        seguimiento = self.proponer()
        equipo.decidir_seguimiento(seguimiento["id"], self.dani["id"], True)
        senal = validar({
            "tipo": "senal_equipo",
            "id": "s-1",
            "seguimiento": seguimiento["id"],
            "secuencia": 1,
            "senal": "avance",
            "payload": {},
            "observada_en": time.time(),
            "schema": 1,
        })
        guardada = equipo.guardar_senal(self.nodo["id"], senal)
        equipo_coordinador.reducir(guardada)
        panel = equipo.panel(self.grupo["id"], self.ana["id"])
        self.assertEqual(panel["tareas"][0]["estado"], "en_progreso")
        self.assertEqual(panel["creencias"][0]["valor"], "en_progreso")
        self.assertIsNone(equipo.guardar_senal(self.nodo["id"], senal))

    def test_un_nodo_no_puede_hablar_por_otro(self):
        seguimiento = self.proponer()
        equipo.decidir_seguimiento(seguimiento["id"], self.dani["id"], True)
        senal = validar({
            "tipo": "senal_equipo", "id": "s-2", "seguimiento": seguimiento["id"],
            "secuencia": 1, "senal": "avance", "payload": {},
            "observada_en": 1_700_000_000.0, "schema": 1,
        })
        with self.assertRaises(equipo.EquipoError):
            equipo.guardar_senal("nodo-ajeno", senal)

    def test_las_rutas_solo_se_ensenan_al_dueno_del_nodo(self):
        self.proponer()
        panel_ana = equipo.panel(self.grupo["id"], self.ana["id"])
        panel_dani = equipo.panel(self.grupo["id"], self.dani["id"])
        self.assertEqual(panel_ana["seguimientos"][0]["parametros"], {})
        self.assertEqual(panel_dani["seguimientos"][0]["parametros"]["ruta"], "/tmp/informe")

    def test_coordinador_propone_sin_conocer_el_id_del_dispositivo(self):
        seguimiento = equipo.proponer_seguimiento(
            self.grupo["id"], self.tarea["id"], self.ana["id"], "",
            "avance", {"ruta": "/tmp/informe"}, "Solo metadatos",
        )
        self.assertEqual(seguimiento["node_id"], self.nodo["id"])
        self.assertEqual(seguimiento["estado"], "propuesto")

    def test_la_observacion_vigente_gana_a_una_declaracion_posterior(self):
        seguimiento = self.proponer()
        equipo.decidir_seguimiento(seguimiento["id"], self.dani["id"], True)
        senal = validar({
            "tipo": "senal_equipo", "id": "s-3", "seguimiento": seguimiento["id"],
            "secuencia": 1, "senal": "avance", "payload": {},
            "observada_en": time.time(), "schema": 1,
        })
        equipo_coordinador.reducir(equipo.guardar_senal(self.nodo["id"], senal))
        creencia = equipo.declarar_estado(
            self.grupo["id"], self.tarea["id"], self.dani["id"], "cerrada"
        )
        self.assertEqual(creencia["procedencia"], "observacion")
        self.assertEqual(creencia["valor"], "en_progreso")

    def test_revocar_hace_caducar_la_creencia_observada(self):
        seguimiento = self.proponer()
        equipo.decidir_seguimiento(seguimiento["id"], self.dani["id"], True)
        senal = validar({
            "tipo": "senal_equipo", "id": "s-4", "seguimiento": seguimiento["id"],
            "secuencia": 1, "senal": "avance", "payload": {},
            "observada_en": time.time(), "schema": 1,
        })
        equipo_coordinador.reducir(equipo.guardar_senal(self.nodo["id"], senal))
        equipo.revocar_seguimiento(seguimiento["id"], self.dani["id"])
        self.assertEqual(
            equipo.panel(self.grupo["id"], self.dani["id"])["creencias"], []
        )

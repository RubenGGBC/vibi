import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app import apariencia, db, equipo
from app.config import settings


class AparienciaTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.patch_db = patch.object(
            settings, "db_path", str(Path(self.tempdir.name) / "vibi.db")
        )
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)
        db.init_db()
        self.ana = db.get_or_create_user("ana")

    def test_tiene_la_identidad_original_hasta_que_la_persona_la_cambia(self):
        identidad = apariencia.obtener(self.ana["id"])
        self.assertEqual(identidad["color_cara"], "#FFFFFF")
        self.assertEqual(identidad["color_antifaz"], "#0C0714")
        self.assertEqual(identidad["color_sombrero"], "#F4121B")

    def test_guarda_y_normaliza_los_tres_colores(self):
        identidad = apariencia.guardar(
            self.ana["id"],
            {
                "color_cara": "#aabbcc",
                "color_antifaz": "#112233",
                "color_sombrero": "#00cc66",
            },
        )
        self.assertEqual(identidad["color_cara"], "#AABBCC")
        self.assertEqual(identidad["color_antifaz"], "#112233")
        self.assertEqual(identidad["color_sombrero"], "#00CC66")

    def test_rechaza_colores_que_el_svg_no_puede_tratar_como_identidad(self):
        with self.assertRaises(apariencia.AparienciaInvalida):
            apariencia.guardar(
                self.ana["id"],
                {
                    "color_cara": "red; background:url(x)",
                    "color_antifaz": "#112233",
                    "color_sombrero": "#00CC66",
                },
            )

    def test_el_equipo_recibe_la_identidad_visual_de_cada_miembro(self):
        apariencia.guardar(
            self.ana["id"],
            {
                "color_cara": "#FFFF00",
                "color_antifaz": "#0033AA",
                "color_sombrero": "#00AA55",
            },
        )
        grupo = equipo.crear("Color", self.ana["id"])
        miembro = grupo["miembros"][0]
        self.assertEqual(miembro["color_cara"], "#FFFF00")
        self.assertEqual(miembro["color_antifaz"], "#0033AA")
        self.assertEqual(miembro["color_sombrero"], "#00AA55")

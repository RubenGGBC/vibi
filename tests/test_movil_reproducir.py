"""Poner una canción concreta y avisar de lo que termina con el móvil en el bolsillo."""
import asyncio
from unittest.mock import AsyncMock, patch

from app import movil, nodes
from tests.test_movil import CAPACIDADES, MovilTestCase


class PonerUnaCancion(MovilTestCase):
    def setUp(self):
        super().setUp()
        self.alta("Galaxy", CAPACIDADES)

    def _reproducir(self, respuestas):
        self.dispatch = AsyncMock(side_effect=respuestas)
        with patch.object(nodes, "dispatch", self.dispatch):
            return asyncio.run(
                movil.ejecutar(
                    self.user,
                    "movil_musica",
                    {"accion": "reproducir", "consulta": "Eye of the Tiger"},
                )
            )

    def test_reproducir_usa_busqueda_directa(self):
        with patch.object(movil, "_buscar_cancion") as buscar:
            resultado = self._reproducir(
                [{"estado": "ok", "resultado": {"sonando": "Eye of the Tiger"}}]
            )
        buscar.assert_not_called()
        self.assertEqual(resultado, {"sonando": "Eye of the Tiger"})

    def test_reproducir_recurre_a_video_id(self):
        no_soportado = {
            "estado": "error",
            "resultado": {"codigo": "no_soportado", "error": "Esta app no busca"},
        }
        with patch.object(movil, "_buscar_cancion", return_value="abc123"):
            resultado = self._reproducir(
                [no_soportado, {"estado": "ok", "resultado": {"sonando": "Eye of the Tiger"}}]
            )
        self.assertEqual(resultado, {"sonando": "Eye of the Tiger"})
        segunda = self.dispatch.call_args_list[1]
        self.assertEqual(segunda.args[2], "movil.media.reproducir")
        self.assertEqual(segunda.args[3], {"video_id": "abc123"})

    def test_busqueda_sin_resultados_devuelve_error(self):
        no_soportado = {
            "estado": "error",
            "resultado": {"codigo": "no_soportado", "error": "Esta app no busca"},
        }
        with patch.object(movil, "_buscar_cancion", return_value=None):
            resultado = self._reproducir([no_soportado])
        self.assertIn("error", resultado)
        self.assertEqual(self.dispatch.call_count, 1)

    def test_fallo_de_la_busqueda_se_cuenta(self):
        no_soportado = {
            "estado": "error",
            "resultado": {"codigo": "no_soportado", "error": "Esta app no busca"},
        }
        with patch.object(movil, "_buscar_cancion", side_effect=RuntimeError("YouTube cambió")):
            resultado = self._reproducir([no_soportado])
        self.assertIn("error", resultado)


class AvisosAlMovil(MovilTestCase):
    def test_tarea_avisa_solo_a_moviles(self):
        pc = self.alta("PC", ["shell.run"])
        galaxy = self.alta("Galaxy", CAPACIDADES)
        enviado = AsyncMock(return_value=True)
        with patch.object(nodes.manager, "send", enviado):
            asyncio.run(movil.notificar_movil(self.user["id"], "Tarea terminada", "t1", False))
        enviado.assert_awaited_once_with(
            galaxy["id"], {"tipo": "notificacion", "texto": "Tarea terminada", "task_id": "t1"}
        )
        self.assertNotEqual(enviado.call_args.args[0], pc["id"])

    def test_lo_leido_en_el_movil_cuenta_como_contenido_ajeno(self):
        self.assertIn("movil.notificaciones.listar", nodes.CAPACIDADES_CON_CONTENIDO_AJENO)
        self.assertIn("movil.pantalla.leer", nodes.CAPACIDADES_CON_CONTENIDO_AJENO)

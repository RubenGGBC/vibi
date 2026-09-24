"""Lo que se le ahorra a `agy` en cada llamada a la interfaz.

Dos cosas del 24/09/2026 (mandar un WhatsApp, 154 s): diez `view_file` de
esquemas antes de poder llamar a nada, y siete resultados de 5-6 KB que `agy`
guardó en archivo y el modelo tuvo que volver a abrir.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from app import tools
from app.executors import agy_firmas, agy_mcp, antigravity_chat


class LasFirmas(unittest.TestCase):
    def test_salen_del_esquema_con_lo_obligatorio_delante(self):
        firma = agy_firmas.firma("devices.key")
        self.assertTrue(firma.startswith("devices_key(key: texto"))
        self.assertIn("count?: entero", firma)

    def test_estan_todas_las_del_escritorio_que_existen(self):
        bloque = agy_firmas.bloque()
        for tool_id in agy_firmas.ESCRITORIO:
            if tool_id in tools.PRIMITIVES:
                self.assertIn(tool_id.replace(".", "_") + "(", bloque)

    def test_solo_las_publicadas_si_se_dice_cuales(self):
        bloque = agy_firmas.bloque(("devices.ui_jev",))
        self.assertIn("devices_ui_jev(", bloque)
        self.assertNotIn("devices_click(", bloque)

    def test_las_acciones_de_un_paso_son_las_que_acepta_el_nodo(self):
        """El esquema dice «texto»: la lista real vive en el nodo."""
        from vibi_node import ui

        self.assertEqual(set(agy_firmas.ACCIONES_PASO), set(ui.ACCIONES))

    def test_el_prompt_las_lleva_y_sobrevive_al_format(self):
        """El bloque pasa por `str.format`: una llave suelta lo rompería."""
        prompt = antigravity_chat.REGLAS_ORDENADOR_PROPIO.format(nombre="Rubén")
        self.assertIn("devices_ui_batch(steps:", prompt)
        self.assertNotIn("{", agy_firmas.bloque())


class ResultadosMasCortos(unittest.TestCase):
    def _orden(self) -> dict:
        return {
            "invocation_id": "i",
            "tool_id": "devices.ui_snapshot",
            "status": "succeeded",
            "result": {
                "device": {
                    "id": "n1",
                    "name": "portatil",
                    "capabilities": ["ui.snapshot"] * 33,
                    "last_seen": 1.0,
                },
                "state": "ok",
                "result": {"arbol": 'ventana con foco: "WhatsApp"\n[e1] botón "Enviar"'},
            },
        }

    def test_del_nodo_solo_queda_el_nombre(self):
        compacto = agy_mcp._compactar(self._orden())
        self.assertEqual(compacto["result"]["device"], "portatil")

    def test_el_arbol_sale_aparte_y_sin_escapar(self):
        orden = self._orden()
        arbol = agy_mcp._separar_arbol(orden)
        self.assertEqual(arbol, 'ventana con foco: "WhatsApp"\n[e1] botón "Enviar"')
        self.assertNotIn("WhatsApp", json.dumps(orden))

    def test_el_de_jev_va_un_nivel_mas_arriba(self):
        orden = {"result": {"terminado": True, "arbol": "[e1] botón"}}
        self.assertEqual(agy_mcp._separar_arbol(orden), "[e1] botón")

    def test_sin_arbol_no_se_toca_nada(self):
        orden = {"result": {"state": "ok", "result": {"status": "launched"}}}
        self.assertIsNone(agy_mcp._separar_arbol(orden))
        self.assertEqual(orden["result"]["result"], {"status": "launched"})

    def test_un_error_pasa_tal_cual(self):
        self.assertEqual(agy_mcp._compactar({"error": "x"}), {"error": "x"})


if __name__ == "__main__":
    unittest.main()

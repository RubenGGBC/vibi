"""Qué está haciendo `agy` en cada momento, con detalle suficiente para verlo.

Hasta ahora del stream solo se sacaban el tipo de paso y su estado, que da para
poner una cara («usando el terminal») pero no para entender nada. Los pasos
traen mucho más —el comando literal, la consulta buscada, el archivo abierto, la
herramienta MCP con su servidor— y es lo que hace falta para mirar por encima
del hombro a Vibi mientras trabaja.

Los ejemplos de aquí están copiados de un `agy` real (19/08/2026), no
inventados: los nombres de campo son suyos y cambiarlos de memoria es la forma
más fácil de escribir una prueba que pasa contra algo que no existe.
"""
import unittest

from app.executors import agy_client


def _paso(tipo, estado="CORTEX_STEP_STATUS_DONE", **campos):
    return {"type": tipo, "status": estado, **campos}


def _envoltorio(*pasos):
    return {"update": {"mainTrajectoryUpdate": {"stepsUpdate": {"steps": list(pasos)}}}}


class ContarQueEstaHaciendo(unittest.TestCase):
    def test_un_comando_se_cuenta_con_el_comando(self):
        crudo = _envoltorio(
            _paso(
                "CORTEX_STEP_TYPE_RUN_COMMAND",
                runCommand={
                    "commandLine": 'Start-Process explorer.exe "$HOME\\Downloads"',
                    "cwd": "C:\\Users\\rebel",
                },
            )
        )

        pasos = agy_client.read_update(crudo).pasos

        self.assertEqual(pasos[0].tipo, "CORTEX_STEP_TYPE_RUN_COMMAND")
        self.assertIn("explorer.exe", pasos[0].detalle)

    def test_una_busqueda_se_cuenta_con_la_consulta(self):
        crudo = _envoltorio(
            _paso("CORTEX_STEP_TYPE_SEARCH_WEB", searchWeb={"query": "torrent castellano"})
        )

        self.assertEqual(
            agy_client.read_update(crudo).pasos[0].detalle, "torrent castellano"
        )

    def test_una_herramienta_de_vibi_dice_cual(self):
        """La forma real que manda `agy`, copiada de una trayectoria viva.

        El nombre va anidado en `toolCall.name`, no suelto al lado del servidor.
        Mirando solo un nivel se cogía `serverName` y la ventana ponía «vibi» a
        secas, que no distingue apagar la música de leerte el correo.
        """
        crudo = _envoltorio(
            _paso(
                "CORTEX_STEP_TYPE_MCP_TOOL",
                mcpTool={
                    "serverName": "vibi",
                    "toolCall": {
                        "id": "call_520796",
                        "name": "media_now_playing",
                        "argumentsJson": "{}",
                    },
                    "resultString": '{"status": "succeeded"}',
                },
            )
        )

        detalle = agy_client.read_update(crudo).pasos[0].detalle

        self.assertIn("media_now_playing", detalle)
        self.assertIn("vibi", detalle)

    def test_el_resultado_de_la_herramienta_no_se_cuela_como_detalle(self):
        """`resultString` puede traer el JSON entero de la respuesta, y eso en
        una línea de la ventana no es información, es ruido."""
        crudo = _envoltorio(
            _paso(
                "CORTEX_STEP_TYPE_MCP_TOOL",
                mcpTool={
                    "serverName": "pc",
                    "toolCall": {"name": "ejecutar", "argumentsJson": "{}"},
                    "resultString": "x" * 400,
                },
            )
        )

        self.assertNotIn("xxxx", agy_client.read_update(crudo).pasos[0].detalle)

    def test_un_tipo_que_no_conocemos_no_se_queda_mudo(self):
        """`agy` estrena tipos de paso sin avisar. Que salga algo, aunque sea
        aproximado, vale más que una línea vacía en la ventana."""
        crudo = _envoltorio(
            _paso("CORTEX_STEP_TYPE_INVENTADO", loQueSea={"path": "/tmp/x.txt"})
        )

        self.assertIn("/tmp/x.txt", agy_client.read_update(crudo).pasos[0].detalle)

    def test_el_andamiaje_no_aparece_como_trabajo(self):
        """La respuesta del modelo no es un paso que mirar: es la respuesta."""
        crudo = _envoltorio(
            _paso("CORTEX_STEP_TYPE_PLANNER_RESPONSE", plannerResponse={"response": "hola"}),
            _paso("CORTEX_STEP_TYPE_CHECKPOINT", checkpoint={"userIntent": "saludo"}),
            _paso("CORTEX_STEP_TYPE_RUN_COMMAND", runCommand={"commandLine": "ls"}),
        )

        pasos = agy_client.read_update(crudo).pasos

        self.assertEqual([p.tipo for p in pasos], ["CORTEX_STEP_TYPE_RUN_COMMAND"])

    def test_lleva_el_estado_para_saber_si_sigue_en_marcha(self):
        crudo = _envoltorio(
            _paso(
                "CORTEX_STEP_TYPE_RUN_COMMAND",
                estado="CORTEX_STEP_STATUS_RUNNING",
                runCommand={"commandLine": "npm install"},
            )
        )

        self.assertTrue(agy_client.read_update(crudo).pasos[0].en_curso)

    def test_un_detalle_larguisimo_se_recorta(self):
        """Un comando puede ocupar mil caracteres y esto va a una ventana."""
        crudo = _envoltorio(
            _paso("CORTEX_STEP_TYPE_RUN_COMMAND", runCommand={"commandLine": "x" * 900})
        )

        self.assertLessEqual(len(agy_client.read_update(crudo).pasos[0].detalle), 300)


class ElNombreQueSeLee(unittest.TestCase):
    def test_los_tipos_se_leen_sin_su_prefijo(self):
        self.assertEqual(
            agy_client.nombre_de_paso("CORTEX_STEP_TYPE_RUN_COMMAND"), "run_command"
        )

    def test_lo_que_no_lleve_prefijo_se_queda_igual(self):
        self.assertEqual(agy_client.nombre_de_paso("Bash"), "Bash")


if __name__ == "__main__":
    unittest.main()

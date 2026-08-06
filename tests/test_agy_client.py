"""El cliente del language server de `agy`: sobres del stream y lectura del texto."""
import io
import json
import struct
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.executors import agy_client


def _sobre(objeto: dict, banderas: int = 0) -> bytes:
    cuerpo = json.dumps(objeto).encode()
    return bytes([banderas]) + struct.pack(">I", len(cuerpo)) + cuerpo


class SobresDelStream(unittest.TestCase):
    """Connect no manda JSON suelto: cada mensaje va con cabecera propia."""

    def test_lee_varios_mensajes_seguidos(self):
        flujo = io.BytesIO(_sobre({"a": 1}) + _sobre({"b": 2}))

        leidos = list(agy_client.read_envelopes(flujo))

        self.assertEqual(leidos, [{"a": 1}, {"b": 2}])


def _update(texto: str, estado: str = "CORTEX_STEP_STATUS_RUNNING") -> dict:
    """Una actualización con la forma que manda el language server."""
    return {
        "update": {
            "mainTrajectoryUpdate": {
                "stepsUpdate": {
                    "steps": [
                        {
                            "type": "CORTEX_STEP_TYPE_PLANNER_RESPONSE",
                            "status": estado,
                            "plannerResponse": {"modifiedResponse": texto},
                        }
                    ]
                }
            }
        }
    }


class TextoDeLaRespuesta(unittest.TestCase):
    def test_saca_el_texto_que_va_escribiendo(self):
        estado = agy_client.read_update(_update("El cielo es azul"))

        self.assertEqual(estado.text, "El cielo es azul")
        self.assertFalse(estado.done)

    def test_reconoce_que_el_turno_ha_terminado(self):
        estado = agy_client.read_update(
            _update("Ya está.", estado="CORTEX_STEP_STATUS_DONE")
        )

        self.assertTrue(estado.done)

    def test_se_queda_con_la_respuesta_mas_reciente(self):
        """El estado inicial del stream trae todos los turnos anteriores.

        Quedarse con el primero devolvía la respuesta más vieja de la
        conversación —la presentación— en cada turno nuevo.
        """
        update = {
            "update": {
                "mainTrajectoryUpdate": {
                    "stepsUpdate": {
                        "steps": [
                            {
                                "type": "CORTEX_STEP_TYPE_PLANNER_RESPONSE",
                                "status": "CORTEX_STEP_STATUS_DONE",
                                "plannerResponse": {"response": "Preparada."},
                            },
                            {
                                "type": "CORTEX_STEP_TYPE_PLANNER_RESPONSE",
                                "status": "CORTEX_STEP_STATUS_RUNNING",
                                "plannerResponse": {"modifiedResponse": "Hace sol"},
                            },
                        ]
                    }
                }
            }
        }

        estado = agy_client.read_update(update)

        self.assertEqual(estado.text, "Hace sol")
        self.assertFalse(estado.done)

    def test_una_actualizacion_sin_respuesta_no_aporta_texto(self):
        """Llegan muchas que son de otras cosas: no deben ensuciar el turno."""
        estado = agy_client.read_update({"update": {"executorMetadata": {}}})

        self.assertIsNone(estado.text)
        self.assertFalse(estado.done)


class TextoNuevoDeCadaTrozo(unittest.TestCase):
    """El stream manda el texto entero cada vez, no solo lo añadido.

    Emitirlo tal cual haría que la cara locutase la respuesta repetida y
    creciendo. Solo puede salir la parte que aún no se ha dicho.
    """

    def test_el_primer_trozo_sale_entero(self):
        turno = agy_client.TurnText()

        self.assertEqual(turno.advance("Hola"), "Hola")

    def test_despues_solo_sale_lo_añadido(self):
        turno = agy_client.TurnText()
        turno.advance("Hola")

        self.assertEqual(turno.advance("Hola, buenas tardes"), ", buenas tardes")

    def test_si_no_ha_cambiado_no_sale_nada(self):
        turno = agy_client.TurnText()
        turno.advance("Hola")

        self.assertIsNone(turno.advance("Hola"))

    def test_si_el_modelo_reescribe_se_emite_lo_nuevo_entero(self):
        """A veces corrige lo ya escrito; entonces no vale con recortar."""
        turno = agy_client.TurnText()
        turno.advance("Hace sol")

        self.assertEqual(turno.advance("Está nublado"), "Está nublado")

    def test_guarda_el_texto_completo_del_turno(self):
        turno = agy_client.TurnText()
        turno.advance("Hola")
        turno.advance("Hola, buenas")

        self.assertEqual(turno.full, "Hola, buenas")


class _Servidor:
    """Un language server de mentira, para no depender de `agy` ni de la red."""

    def __init__(self, respuestas: dict[str, bytes], estado: int = 200):
        self.recibido: list[tuple[str, dict]] = []
        respuestas_ = respuestas
        recibido = self.recibido

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                largo = int(self.headers.get("content-length", 0))
                cuerpo = self.rfile.read(largo)
                try:
                    recibido.append((self.path, json.loads(cuerpo or b"{}")))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # El stream manda el sobre binario de Connect, no JSON.
                    recibido.append((self.path, {"crudo": cuerpo.decode("latin1")}))
                metodo = self.path.rsplit("/", 1)[-1]
                if metodo not in respuestas_:
                    self.send_response(404)
                    self.end_headers()
                    return
                datos = respuestas_[metodo]
                self.send_response(estado)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def log_message(self, *_):  # silencio en la salida de los tests
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def cerrar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class LlamadasAlServidor(unittest.TestCase):
    def _servidor(self, respuestas, estado=200) -> _Servidor:
        servidor = _Servidor(respuestas, estado)
        self.addCleanup(servidor.cerrar)
        return servidor

    def test_encuentra_la_conversacion_activa(self):
        servidor = self._servidor({
            "GetAllCascadeTrajectories": json.dumps({
                "trajectorySummaries": {
                    "abc-123": {"status": "CASCADE_RUN_STATUS_RUNNING"}
                }
            }).encode()
        })

        cliente = agy_client.AgyClient(servidor.port)

        self.assertEqual(cliente.conversations(), ["abc-123"])
        ruta, _ = servidor.recibido[0]
        self.assertEqual(
            ruta, f"/{agy_client.SERVICE}/GetAllCascadeTrajectories"
        )

    def test_sin_conversaciones_devuelve_lista_vacia(self):
        servidor = self._servidor(
            {"GetAllCascadeTrajectories": json.dumps({}).encode()}
        )

        self.assertEqual(agy_client.AgyClient(servidor.port).conversations(), [])

    def test_un_error_del_servidor_se_convierte_en_excepcion(self):
        """Si `agy` cambia de formato, el turno tiene que poder caer a Claude."""
        servidor = self._servidor({"GetAllCascadeTrajectories": b"{}"}, estado=500)

        cliente = agy_client.AgyClient(servidor.port)

        with self.assertRaises(agy_client.AgyError):
            cliente.conversations()

    def test_cortar_un_turno_manda_la_conversacion(self):
        servidor = self._servidor({"ForceStopCascadeTree": b"{}"})

        agy_client.AgyClient(servidor.port).stop("abc-123")

        ruta, cuerpo = servidor.recibido[0]
        self.assertTrue(ruta.endswith("/ForceStopCascadeTree"))
        self.assertEqual(cuerpo, {"conversationId": "abc-123"})


class SeguirElTurnoPorElStream(unittest.TestCase):
    def _servidor(self, respuestas) -> _Servidor:
        servidor = _Servidor(respuestas)
        self.addCleanup(servidor.cerrar)
        return servidor

    def test_va_entregando_el_texto_segun_llega(self):
        servidor = self._servidor({
            "StreamAgentStateUpdates": (
                _sobre(_update("Hace"))
                + _sobre(_update("Hace sol"))
                + _sobre(_update("Hace sol.", estado="CORTEX_STEP_STATUS_DONE"))
            )
        })

        recibidos = list(
            agy_client.AgyClient(servidor.port).stream_updates("abc-123")
        )

        self.assertEqual([u.text for u in recibidos], ["Hace", "Hace sol", "Hace sol."])
        self.assertTrue(recibidos[-1].done)

    def test_se_para_en_cuanto_el_turno_termina(self):
        """Lo que venga después del DONE es de otro turno: no debe colarse."""
        servidor = self._servidor({
            "StreamAgentStateUpdates": (
                _sobre(_update("Ya está.", estado="CORTEX_STEP_STATUS_DONE"))
                + _sobre(_update("de otro turno"))
            )
        })

        recibidos = list(
            agy_client.AgyClient(servidor.port).stream_updates("abc-123")
        )

        self.assertEqual([u.text for u in recibidos], ["Ya está."])

    def test_ignora_las_actualizaciones_que_no_traen_respuesta(self):
        servidor = self._servidor({
            "StreamAgentStateUpdates": (
                _sobre({"update": {"executorMetadata": {}}})
                + _sobre(_update("Hola", estado="CORTEX_STEP_STATUS_DONE"))
            )
        })

        recibidos = list(
            agy_client.AgyClient(servidor.port).stream_updates("abc-123")
        )

        self.assertEqual([u.text for u in recibidos], ["Hola"])

    def test_el_eco_del_turno_anterior_no_cierra_el_nuevo(self):
        """Al abrir, el servidor vuelca la respuesta anterior ya terminada.

        Como viene marcada como DONE, cortar ahí dejaría el turno nuevo sin
        leer y devolvería lo que Morgana ya había dicho.
        """
        servidor = self._servidor({
            "StreamAgentStateUpdates": (
                _sobre(_update("Preparada.", estado="CORTEX_STEP_STATUS_DONE"))
                + _sobre(_update("Hace"))
                + _sobre(_update("Hace sol.", estado="CORTEX_STEP_STATUS_DONE"))
            )
        })

        recibidos = list(
            agy_client.AgyClient(servidor.port).stream_updates(
                "abc-123", skip_text="Preparada."
            )
        )

        self.assertEqual([u.text for u in recibidos], ["Hace", "Hace sol."])

    def test_se_conecta_al_pedirlo_y_no_al_leerlo(self):
        """El turno se teclea justo después de abrir el stream.

        Si la conexión se hiciera perezosamente, al primer `next`, el turno
        entraría antes de estar escuchando y se perdería su principio.
        """
        servidor = self._servidor({
            "StreamAgentStateUpdates": _sobre(
                _update("ok", estado="CORTEX_STEP_STATUS_DONE")
            )
        })

        agy_client.AgyClient(servidor.port).stream_updates("abc-123")

        self.assertEqual(len(servidor.recibido), 1)

    def test_pide_el_stream_con_el_sobre_de_connect(self):
        """No es JSON suelto: el servidor rechaza la petición sin cabecera."""
        servidor = self._servidor({
            "StreamAgentStateUpdates": _sobre(
                _update("ok", estado="CORTEX_STEP_STATUS_DONE")
            )
        })

        list(agy_client.AgyClient(servidor.port).stream_updates("abc-123"))

        _, cuerpo = servidor.recibido[0]
        # El cuerpo llega con cabecera binaria, así que no es JSON directo.
        self.assertIn("crudo", cuerpo)
        self.assertIn("abc-123", cuerpo["crudo"])

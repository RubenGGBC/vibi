"""La sesión de la cara es efímera: al cerrarla, el próximo despertar empieza en blanco."""
from unittest.mock import AsyncMock, patch

from app import db
from app.core.messages import ResultadoMensaje
from tests.test_nodes import NodeTestCase


class SesionDeVozEfimera(NodeTestCase):
    def setUp(self):
        super().setUp()
        token = self.registrar(nodo="Sobremesa").json()["token"]
        self.node_headers = {"Authorization": f"Bearer {token}"}

    def _conversacion_con_historia(self) -> str:
        conversation = db.get_or_create_active_conversation(self.user["id"])
        db.add_conversation_message(conversation["id"], "user", "hola", "cara")
        return conversation["id"]

    def test_cerrar_archiva_la_conversacion_y_deja_una_vacia(self):
        anterior = self._conversacion_con_historia()

        response = self.client.post("/api/voz/cerrar", headers=self.node_headers)

        self.assertEqual(response.status_code, 200)
        actual = db.get_active_conversation(self.user["id"])
        self.assertNotEqual(actual["id"], anterior)
        self.assertEqual(response.json()["conversation_id"], actual["id"])
        self.assertEqual(db.list_context_messages(actual["id"], 4000), [])

    def test_la_despedida_archiva_sin_esperar_a_que_el_cliente_lo_pida(self):
        anterior = self._conversacion_con_historia()

        with patch(
            "app.api.groq_speech.transcribir",
            AsyncMock(return_value="Gracias, Vibi"),
        ):
            response = self.client.post(
                "/api/voz",
                headers=self.node_headers,
                files={"audio": ("voz.webm", b"clip", "audio/webm")},
                data={
                    "conversation_mode": "true",
                    "conversation_id": anterior,
                },
            )

        self.assertEqual(response.json()["via"], "cerrar")
        actual = db.get_active_conversation(self.user["id"])
        self.assertNotEqual(actual["id"], anterior)

    def test_una_pregunta_normal_no_corta_la_conversacion(self):
        anterior = self._conversacion_con_historia()

        with patch(
            "app.api.groq_speech.transcribir",
            AsyncMock(return_value="¿Qué tiempo hace?"),
        ), patch(
            "app.api.message_core.procesar_mensaje",
            AsyncMock(return_value=ResultadoMensaje("rapida", respuesta="Hace sol.")),
        ):
            response = self.client.post(
                "/api/voz",
                headers=self.node_headers,
                files={"audio": ("voz.webm", b"clip", "audio/webm")},
                data={
                    "conversation_mode": "true",
                    "conversation_id": anterior,
                },
            )

        self.assertEqual(response.json()["via"], "rapida")
        self.assertEqual(db.get_active_conversation(self.user["id"])["id"], anterior)

    def test_cerrar_exige_autenticacion(self):
        response = self.client.post("/api/voz/cerrar")

        self.assertEqual(response.status_code, 401)


class ElMotorSeMontaCuandoHayVoz(NodeTestCase):
    """Abrir el canal no es hablar, y montar el motor no sale gratis.

    El detector de la palabra clave se equivoca: acepta «vibi», «bibi» y
    «vivi», que son sílabas que aparecen sueltas en cualquier conversación.
    Medido en este equipo sobre 48 h, de nueve aperturas del canal seis no
    llevaron detrás ni un solo clip de audio.

    Cada una de esas seis montaba el motor, y montar el motor abre el
    navegador del usuario en su ordenador —Opera entero, con sus pestañas—
    porque `_process_for` asegura Playwright antes de arrancar `agy`. De ahí
    que Opera apareciera solo cada pocas horas sin que nadie lo hubiera pedido.
    """

    def setUp(self):
        super().setUp()
        token = self.registrar(nodo="Sobremesa").json()["token"]
        self.node_headers = {"Authorization": f"Bearer {token}"}

    def test_abrir_el_canal_no_monta_el_motor(self):
        with patch("app.api.chat.precalentar_en_segundo_plano") as precalentar:
            response = self.client.post("/api/voz/abrir", headers=self.node_headers)

        self.assertEqual(response.status_code, 200)
        precalentar.assert_not_called()

    def test_el_audio_monta_el_motor_mientras_se_transcribe(self):
        # El hueco que aprovechaba el precalentado sigue estando: se lanza
        # antes de pedirle la transcripción a Groq, no después.
        conversation = db.get_or_create_active_conversation(self.user["id"])

        with patch(
            "app.api.chat.precalentar_en_segundo_plano"
        ) as precalentar, patch(
            "app.api.groq_speech.transcribir",
            AsyncMock(return_value="¿Qué hora es?"),
        ), patch(
            "app.api.message_core.procesar_mensaje",
            AsyncMock(return_value=ResultadoMensaje("rapida", respuesta="Las tres.")),
        ):
            response = self.client.post(
                "/api/voz",
                headers=self.node_headers,
                files={"audio": ("voz.webm", b"clip", "audio/webm")},
                data={
                    "conversation_mode": "true",
                    "conversation_id": conversation["id"],
                },
            )

        self.assertEqual(response.status_code, 200)
        precalentar.assert_called_once()

"""Pruebas del detector local de la palabra «Morgana».

El sidecar corre en el PC del usuario, donde el micrófono puede no estar listo
al arrancar Windows o desaparecer a media sesión (unos auriculares que se
apagan). Estas pruebas fijan que el detector aguante ambas cosas en lugar de
morir en silencio y dejar a Morgana sorda.
"""

import sys
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

WAKE_DIR = Path(__file__).resolve().parents[1] / "frontend" / "src-tauri" / "wake"


class FakeStream:
    """Sustituto de sd.RawInputStream que no toca hardware."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


def _install_audio_doubles():
    """Registra dobles de sounddevice y vosk antes de importar el sidecar."""
    sounddevice = types.ModuleType("sounddevice")
    sounddevice.RawInputStream = FakeStream
    sounddevice.CallbackFlags = type("CallbackFlags", (), {})
    sounddevice.query_devices = lambda device=None, kind=None: {
        "default_samplerate": 48000.0
    }
    sys.modules["sounddevice"] = sounddevice

    vosk = types.ModuleType("vosk")
    vosk.Model = lambda path: types.SimpleNamespace(path=path)
    vosk.KaldiRecognizer = lambda *args: types.SimpleNamespace(args=args)
    vosk.SetLogLevel = lambda level: None
    sys.modules["vosk"] = vosk


_install_audio_doubles()
sys.path.insert(0, str(WAKE_DIR))
import wake_listener  # noqa: E402


class BackoffTests(TestCase):
    def test_la_espera_crece_y_se_satura(self):
        esperas = [wake_listener.backoff_delay(intento) for intento in range(1, 8)]
        self.assertEqual(esperas[0], wake_listener.RETRY_BASE_SECONDS)
        for anterior, siguiente in zip(esperas, esperas[1:]):
            self.assertGreaterEqual(siguiente, anterior)
        self.assertLessEqual(max(esperas), wake_listener.RETRY_MAX_SECONDS)
        self.assertEqual(esperas[-1], wake_listener.RETRY_MAX_SECONDS)

    def test_sin_fallos_no_se_espera(self):
        self.assertEqual(wake_listener.backoff_delay(0), 0.0)


class ArranqueEnFrioTests(TestCase):
    """Al iniciar sesión en Windows el micrófono puede tardar en existir."""

    def test_construir_el_listener_no_consulta_el_dispositivo(self):
        def explota(*args, **kwargs):
            raise OSError("Error querying device -1")

        with patch.object(wake_listener.sd, "query_devices", explota):
            # Antes esto reventaba en __init__ y el proceso moría con código 1.
            listener = wake_listener.WakeListener(Path("modelo"))

        self.assertIsNone(listener.stream)

    def test_un_microfono_ausente_no_mata_el_proceso_y_reintenta(self):
        listener = wake_listener.WakeListener(Path("modelo"))

        def explota(*args, **kwargs):
            raise OSError("Error opening RawInputStream")

        emitidos = []
        with patch.object(wake_listener.sd, "query_devices", explota), patch.object(
            wake_listener, "emit", lambda tipo, **carga: emitidos.append((tipo, carga))
        ):
            listener.ensure_stream(now=100.0)

        self.assertIsNone(listener.stream)
        self.assertEqual(listener.failures, 1)
        self.assertGreater(listener.next_attempt, 100.0)
        self.assertEqual([tipo for tipo, _ in emitidos], ["warning"])

    def test_no_reintenta_antes_de_tiempo_pero_acaba_abriendo(self):
        listener = wake_listener.WakeListener(Path("modelo"))
        listener.failures = 1
        listener.next_attempt = 200.0

        with patch.object(wake_listener, "emit", lambda *a, **k: None):
            listener.ensure_stream(now=199.0)
            self.assertIsNone(listener.stream, "no debe reintentar antes de tiempo")

            listener.ensure_stream(now=201.0)

        self.assertIsNotNone(listener.stream)
        self.assertTrue(listener.stream.started)
        self.assertEqual(listener.failures, 0, "un éxito reinicia el backoff")


class MicrofonoQueDesapareceTests(TestCase):
    """Los auriculares del mando se apagan solos y el stream deja de dar audio."""

    def _listener_escuchando(self):
        listener = wake_listener.WakeListener(Path("modelo"))
        with patch.object(wake_listener, "emit", lambda *a, **k: None):
            listener.ensure_stream(now=0.0)
        return listener

    def test_un_stream_mudo_se_considera_caido(self):
        listener = self._listener_escuchando()
        listener.last_audio = 0.0

        justo_antes = wake_listener.AUDIO_STALL_SECONDS - 0.1
        self.assertFalse(listener.audio_is_stalled(justo_antes))
        self.assertTrue(listener.audio_is_stalled(wake_listener.AUDIO_STALL_SECONDS + 0.1))

    def test_en_pausa_el_silencio_es_normal(self):
        listener = self._listener_escuchando()
        listener.last_audio = 0.0
        listener.paused = True

        self.assertFalse(listener.audio_is_stalled(wake_listener.AUDIO_STALL_SECONDS * 10))

    def test_tras_caerse_vuelve_a_abrir_el_stream(self):
        listener = self._listener_escuchando()
        primero = listener.stream
        listener.last_audio = 0.0

        with patch.object(wake_listener, "emit", lambda *a, **k: None):
            listener.recover_stalled_stream(now=wake_listener.AUDIO_STALL_SECONDS + 1)
            listener.ensure_stream(now=wake_listener.AUDIO_STALL_SECONDS + 1)

        self.assertTrue(primero.closed, "el stream muerto debe cerrarse")
        self.assertIsNotNone(listener.stream)
        self.assertIsNot(listener.stream, primero, "debe ser un stream nuevo")


class ReanudarTests(TestCase):
    def test_reanudar_no_falla_aunque_el_microfono_siga_ausente(self):
        listener = wake_listener.WakeListener(Path("modelo"))
        listener.paused = True

        def explota(*args, **kwargs):
            raise OSError("sin micrófono")

        emitidos = []
        with patch.object(wake_listener.sd, "query_devices", explota), patch.object(
            wake_listener, "emit", lambda tipo, **carga: emitidos.append((tipo, carga))
        ):
            listener.set_paused(False)

        # Reanudar sólo cambia el estado: abrir es tarea del bucle, que reintenta.
        self.assertFalse(listener.paused)
        self.assertIn("resumed", [tipo for tipo, _ in emitidos])

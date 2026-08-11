"""Detector local de la palabra «Vibi» para el companion de Windows.

El proceso no conserva audio ni usa red. Habla JSONL por stdout con Tauri y
acepta ``pause``, ``resume`` y ``quit`` por stdin.
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import unicodedata
from collections import deque
from pathlib import Path
from typing import Any

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel


KEYWORD = "vibi"
ACOUSTIC_KEYWORD = "bibi"
WAKE_FORMS = frozenset({KEYWORD, ACOUSTIC_KEYWORD, "vivi"})
# El modelo español no incluye «vibi» en su vocabulario, pero sí «bibi», que
# usa la gramática restringida; al reexaminar la misma pronunciación con el
# vocabulario completo devuelve «viví». La marca y el evento siguen siendo
# «vibi»; estas formas sólo existen dentro del reconocimiento acústico.
GRAMMAR = json.dumps([ACOUSTIC_KEYWORD, "[unk]"], ensure_ascii=False)
DEBOUNCE_SECONDS = 2.0
# La gramática restringida sólo sabe decir «bibi» o «[unk]», así que empuja
# hacia «bibi» cualquier cosa que suene parecido: «manzana» llega a salir con
# confianza 1.00. Por eso un candidato se confirma después contra el vocabulario
# completo, que sí tiene palabras de verdad entre las que elegir.
MIN_CONFIDENCE = 0.8
VERIFY_SECONDS = 3.0
# Al iniciar sesión en Windows el micrófono puede tardar en existir, y unos
# auriculares inalámbricos pueden marcharse a media sesión. En vez de morir
# reintentamos indefinidamente, espaciando los intentos.
RETRY_BASE_SECONDS = 1.0
RETRY_MAX_SECONDS = 30.0
# PortAudio no siempre avisa de que un dispositivo ha desaparecido: el stream
# sigue «abierto» pero deja de entregar bloques. Ese silencio es la señal.
AUDIO_STALL_SECONDS = 10.0


def backoff_delay(failures: int) -> float:
    """Espera antes del siguiente intento: 1, 2, 4… hasta el tope."""
    if failures <= 0:
        return 0.0
    return min(RETRY_BASE_SECONDS * 2 ** (failures - 1), RETRY_MAX_SECONDS)


def emit(event_type: str, **payload: Any) -> None:
    print(
        json.dumps({"type": event_type, **payload}, ensure_ascii=False),
        flush=True,
    )


def normalize(text: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(without_accents.split())


class WakeListener:
    def __init__(self, model_path: Path, device: int | str | None = None) -> None:
        self.model = Model(str(model_path))
        self.device = device
        # El dispositivo se consulta al abrir el stream, no aquí: construir el
        # detector nunca debe fallar porque el micrófono aún no esté listo.
        self.sample_rate = 0
        self.audio: queue.Queue[bytes] = queue.Queue(maxsize=32)
        self.commands: queue.Queue[str] = queue.Queue()
        self.stream: sd.RawInputStream | None = None
        self.recognizer: KaldiRecognizer | None = None
        self.paused = False
        self.quitting = False
        self.last_wake = 0.0
        self.failures = 0
        self.next_attempt = 0.0
        self.last_audio = 0.0
        self.recent: deque[bytes] = deque()
        self.recent_bytes = 0

    def _new_recognizer(self) -> KaldiRecognizer:
        recognizer = KaldiRecognizer(self.model, self.sample_rate, GRAMMAR)
        # Necesitamos el desglose por palabra para leer su confianza.
        recognizer.SetWords(True)
        return recognizer

    def remember(self, data: bytes) -> None:
        """Guarda los últimos segundos de audio para poder reexaminarlos."""
        self.recent.append(data)
        self.recent_bytes += len(data)
        limite = int(VERIFY_SECONDS * self.sample_rate * 2)
        while self.recent_bytes > limite and len(self.recent) > 1:
            self.recent_bytes -= len(self.recent.popleft())

    def forget(self) -> None:
        self.recent.clear()
        self.recent_bytes = 0

    def heard_keyword(self, result: dict[str, Any]) -> bool:
        """Primera etapa: ¿dijo la palabra, y con qué seguridad?"""
        palabras = result.get("result") or []
        if palabras:
            return any(
                normalize(str(palabra.get("word", ""))) in WAKE_FORMS
                and float(palabra.get("conf", 0.0)) >= MIN_CONFIDENCE
                for palabra in palabras
            )
        return bool(WAKE_FORMS.intersection(normalize(str(result.get("text", ""))).split()))

    def confirm_keyword(self) -> bool:
        """Segunda etapa: reexamina el audio con el vocabulario completo.

        Sin gramática el modelo puede responder «manzana» o «mora», que es justo
        lo que distingue un despertar real de uno imaginado.
        """
        if not self.recent:
            return False
        verifier = KaldiRecognizer(self.model, self.sample_rate)
        verifier.AcceptWaveform(b"".join(self.recent))
        texto = json.loads(verifier.FinalResult()).get("text", "")
        return bool(WAKE_FORMS.intersection(normalize(str(texto)).split()))

    def _audio_callback(
        self,
        data: bytes,
        _frames: int,
        _time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            print(f"audio: {status}", file=sys.stderr, flush=True)
        try:
            self.audio.put_nowait(bytes(data))
        except queue.Full:
            # Ante carga puntual preferimos perder el bloque más antiguo a
            # retrasar la detección varios segundos.
            try:
                self.audio.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio.put_nowait(bytes(data))
            except queue.Full:
                pass

    def open_stream(self) -> None:
        """Abre el micrófono. Propaga la excepción; el reintento va aparte."""
        device_info = sd.query_devices(self.device, "input")
        self.sample_rate = int(device_info["default_samplerate"])
        self.recognizer = self._new_recognizer()
        self.audio = queue.Queue(maxsize=32)
        # El audio de antes del corte ya no describe lo que se está diciendo.
        self.forget()
        self.stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=4_000,
            device=self.device,
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
        )
        self.stream.start()

    def ensure_stream(self, now: float) -> None:
        """Mantiene el micrófono abierto, reintentando con espera creciente."""
        if self.stream is not None or self.paused or self.quitting:
            return
        if now < self.next_attempt:
            return
        try:
            self.open_stream()
        except Exception as error:
            self.close_stream()
            self.failures += 1
            espera = backoff_delay(self.failures)
            self.next_attempt = now + espera
            emit(
                "warning",
                message=f"No se pudo abrir el micrófono: {error}",
                retry_in=espera,
                attempt=self.failures,
            )
            return
        self.failures = 0
        self.next_attempt = 0.0
        self.last_audio = now
        emit("listening", sample_rate=self.sample_rate)

    def audio_is_stalled(self, now: float) -> bool:
        """Un stream abierto que lleva demasiado sin dar audio está muerto."""
        if self.stream is None or self.paused or self.quitting:
            return False
        return now - self.last_audio > AUDIO_STALL_SECONDS

    def recover_stalled_stream(self, now: float) -> None:
        self.close_stream()
        # No es un fallo de apertura: queremos reabrir de inmediato.
        self.failures = 0
        self.next_attempt = now
        emit("warning", message="El micrófono dejó de enviar audio; reabriendo")

    def close_stream(self) -> None:
        stream, self.stream = self.stream, None
        if stream is None:
            return
        # Cerrar un dispositivo que ya se ha desconectado lanza; da igual, lo
        # estamos soltando de todas formas y no puede tumbar el detector.
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def set_paused(self, paused: bool) -> None:
        if self.paused == paused:
            return
        self.paused = paused
        if paused:
            self.close_stream()
            emit("paused")
        else:
            # Reanudar sólo cambia el estado; abrir el micrófono es tarea del
            # bucle, que sabe reintentar si todavía no está disponible.
            self.failures = 0
            self.next_attempt = 0.0
            emit("resumed")

    def handle_command(self, command: str) -> None:
        if command == "pause":
            self.set_paused(True)
        elif command == "resume":
            self.set_paused(False)
        elif command == "quit":
            self.quitting = True
            self.close_stream()

    def detect(self, data: bytes) -> None:
        if self.recognizer is None:
            return
        self.remember(data)
        # Sólo decidimos con resultados finales. Un parcial dice «vibi» en
        # cuanto oye «mor», y eso despertaba a Vibi con «mora» o «borrador».
        if not self.recognizer.AcceptWaveform(data):
            return
        if not self.heard_keyword(json.loads(self.recognizer.Result())):
            return
        if not self.confirm_keyword():
            return
        now = time.monotonic()
        if now - self.last_wake < DEBOUNCE_SECONDS:
            return
        self.last_wake = now
        self.forget()
        emit("wake", keyword=KEYWORD)
        # Pausa inmediatamente: Tauri confirmará la orden, pero no esperamos
        # ese viaje para liberar el micro que va a usar MediaRecorder.
        self.set_paused(True)

    def run(self) -> None:
        threading.Thread(target=self._read_commands, daemon=True).start()
        try:
            emit("ready")
            while not self.quitting:
                self._drain_commands()
                if self.quitting:
                    break
                if self.paused:
                    time.sleep(0.05)
                    continue
                now = time.monotonic()
                if self.audio_is_stalled(now):
                    self.recover_stalled_stream(now)
                self.ensure_stream(now)
                if self.stream is None:
                    # Sin micrófono todavía; el backoff decide cuándo reintentar.
                    time.sleep(0.05)
                    continue
                try:
                    data = self.audio.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.last_audio = time.monotonic()
                self.detect(data)
        finally:
            self.close_stream()

    def _read_commands(self) -> None:
        for line in sys.stdin:
            command = line.strip().casefold()
            if command:
                self.commands.put(command)
            if command == "quit":
                return

    def _drain_commands(self) -> None:
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                return
            self.handle_command(command)


def parse_device(raw: str | None) -> int | str | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device")
    args = parser.parse_args()

    if not args.model.is_dir():
        emit("error", message=f"Modelo Vosk no encontrado: {args.model}")
        return 2

    SetLogLevel(-1)
    try:
        WakeListener(args.model, parse_device(args.device)).run()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        emit("error", message=str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

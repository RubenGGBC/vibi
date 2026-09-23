"""La voz de Vibi, generada en este Mac: Kokoro-82M sobre MLX.

Hasta el 23/09/2026 cada frase iba a los servidores de Microsoft (edge-tts) y
volvía como MP3. Pronunciaba bien, pero cada viaje costaba ~0,7 s aunque la
frase fuera «Vale.», y el MP3 traía casi dos segundos de silencio de relleno
que se oían entre muletilla y respuesta.

Esto hace lo mismo sin salir del Mac. Se eligió midiendo, con las mismas tres
frases, cuánto tarda cada modelo y cuántas palabras entiende mal Whisper al
transcribir lo que dice (una forma de medir la pronunciación sin oírla):

    modelo                    RTF en M1   error de Whisper
    edge-tts (nube, actual)       —            3,8 %   0,71 s la frase corta
    Kokoro-82M (MLX)            0,13           3,8 %   0,26 s la frase corta
    Piper es_ES                 0,03         9,6-15 %  tropieza con el inglés
    Qwen3-TTS 0.6B (MLX)        1,26            25 %   se inventa media frase
    Chatterbox multilingüe      2,46           3,8 %   demasiado lento

(RTF: segundos de cálculo por segundo de audio; por debajo de 1 va más rápido
de lo que se habla. El 3,8 % es el suelo: Whisper escribe «9» por «nueve».)

Kokoro es el único que pronuncia como la voz de la nube y va sobrado en un M1.
En un M4 va más rápido todavía. Corre en la GPU del chip a través de MLX.

Es un servicio aparte, con su entorno propio (Python 3.12), y no una librería
del core: MLX y sus dependencias pesan y el core corre en 3.14. Se queda con el
modelo cargado, porque cargarlo son ~10 s y aquí se pide voz frase a frase.

    POST /tts     {"texto": "...", "voz": "ef_dora", "velocidad": 1.0} -> audio/wav
    GET  /salud   {"ok": true, "modelo": ..., "voz": ...}

Solo escucha en 127.0.0.1: quien lo usa es el core, en esta misma máquina.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

log = logging.getLogger("vibi.voz")

MODELO = "mlx-community/Kokoro-82M-bf16"
VOZ = "ef_dora"
# Las voces en español de Kokoro. `ef_` femenina, `em_` masculinas.
VOCES = ("ef_dora", "em_alex", "em_santa")
# 8931-8933 son del nodo (navegador, MCP del sistema, avisos).
PUERTO = 8940
MAX_TEXTO = 2000
MAX_CUERPO = 64 * 1024

# Lo que el fonetizador en español lee letra a letra. Se escribe como suena, y
# Whisper lo vuelve a entender: medido, «GitHub» salía «HITV» y «Guitjab» sale
# «GitHub». Solo lo que se ha visto fallar; lo demás (Google, WhatsApp,
# YouTube, Spotify, email) ya lo dice bien tal cual.
PRONUNCIACION = {
    "GitHub": "Guitjab",
    "GitLab": "Guitlab",
    "git": "guit",
}

# Kokoro en español no trocea solo: lo que no lleva salto de línea puede salir
# cortado. Se parte por frases, que además da pausas naturales entre ellas.
_FIN_DE_FRASE = re.compile(r"(?<=[.!?…;:])\s+")


def preparar(texto: str) -> str:
    limpio = " ".join(texto.split())
    for palabra, dicha in PRONUNCIACION.items():
        limpio = re.sub(rf"\b{re.escape(palabra)}\b", dicha, limpio, flags=re.IGNORECASE)
    return _FIN_DE_FRASE.sub("\n", limpio)


def recortar_silencio(audio: np.ndarray, sr: int, umbral: float = 0.01,
                      margen_s: float = 0.04) -> np.ndarray:
    """Quita el silencio de los extremos, dejando un respiro.

    Entre muletilla y respuesta, cada décima de silencio se oye como duda.
    """
    sonoro = np.flatnonzero(np.abs(audio) > umbral)
    if sonoro.size == 0:
        return audio
    margen = int(sr * margen_s)
    return audio[max(0, sonoro[0] - margen): sonoro[-1] + 1 + margen]


def a_wav(audio: np.ndarray, sr: int) -> bytes:
    import soundfile as sf

    salida = io.BytesIO()
    sf.write(salida, audio, sr, format="WAV", subtype="PCM_16")
    return salida.getvalue()


class Voz:
    """El modelo cargado. Un único hilo lo usa a la vez: la GPU es una."""

    def __init__(self, modelo: str, voz: str) -> None:
        from mlx_audio.tts.utils import load_model

        inicio = time.perf_counter()
        self.nombre = modelo
        self.voz = voz
        self._modelo = load_model(modelo)
        self.sr = int(self._modelo.sample_rate)
        self._lock = threading.Lock()
        # La primera generación compila y carga el fonetizador: que no la
        # pague la primera frase de verdad.
        for v in VOCES:
            self.sintetizar("Hola.", voz=v)
        log.info("Voz lista en %.1f s (%s, %s)", time.perf_counter() - inicio, modelo, voz)

    def sintetizar(self, texto: str, voz: str | None = None, velocidad: float = 1.0) -> np.ndarray:
        preparado = preparar(texto)
        if not preparado:
            raise ValueError("No hay texto que sintetizar")
        with self._lock:
            trozos = [
                np.asarray(r.audio, dtype=np.float32).reshape(-1)
                for r in self._modelo.generate(
                    preparado, voice=voz or self.voz, speed=velocidad, lang_code="e"
                )
            ]
        if not trozos:
            raise RuntimeError("El modelo no devolvió audio")
        return recortar_silencio(np.concatenate(trozos), self.sr)


def servidor(voz: Voz, host: str, puerto: int) -> ThreadingHTTPServer:
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, formato, *args):  # noqa: D401 - a nuestro log
            log.debug("%s " + formato, self.address_string(), *args)

        def _json(self, estado: int, cuerpo: dict) -> None:
            datos = json.dumps(cuerpo, ensure_ascii=False).encode()
            self.send_response(estado)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self):
            if self.path == "/salud":
                self._json(200, {"ok": True, "modelo": voz.nombre, "voz": voz.voz,
                                 "voces": list(VOCES)})
            else:
                self._json(404, {"error": "no existe"})

        def do_POST(self):
            if self.path != "/tts":
                return self._json(404, {"error": "no existe"})
            longitud = int(self.headers.get("Content-Length") or 0)
            if longitud <= 0 or longitud > MAX_CUERPO:
                return self._json(413, {"error": "cuerpo vacío o demasiado grande"})
            try:
                pedido = json.loads(self.rfile.read(longitud))
                texto = str(pedido.get("texto") or "").strip()
                elegida = str(pedido.get("voz") or "") or None
                velocidad = float(pedido.get("velocidad") or 1.0)
            except (ValueError, TypeError, AttributeError):
                return self._json(400, {"error": "JSON no válido"})
            if not texto:
                return self._json(400, {"error": "No hay texto que sintetizar"})
            if len(texto) > MAX_TEXTO:
                return self._json(413, {"error": "El texto es demasiado largo"})
            if elegida is not None and elegida not in VOCES:
                return self._json(400, {"error": f"voz desconocida: {elegida}"})
            if not 0.5 <= velocidad <= 2.0:
                return self._json(400, {"error": "velocidad fuera de rango"})
            inicio = time.perf_counter()
            try:
                audio = voz.sintetizar(texto, voz=elegida, velocidad=velocidad)
            except Exception as error:  # noqa: BLE001 - se cuenta y se sigue
                log.exception("No se pudo sintetizar")
                return self._json(500, {"error": str(error)[:200]})
            wav = a_wav(audio, voz.sr)
            log.info("%d caracteres en %.2f s (%.1f s de audio)", len(texto),
                     time.perf_counter() - inicio, len(audio) / voz.sr)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.end_headers()
            self.wfile.write(wav)

    return ThreadingHTTPServer((host, puerto), Manejador)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--puerto", type=int, default=PUERTO)
    parser.add_argument("--modelo", default=MODELO)
    parser.add_argument("--voz", default=VOZ, choices=VOCES)
    parser.add_argument("--descargar", action="store_true",
                        help="Carga el modelo (descargándolo si falta) y sale")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    voz = Voz(args.modelo, args.voz)
    if args.descargar:
        return
    http = servidor(voz, args.host, args.puerto)
    log.info("Escuchando en http://%s:%d", args.host, args.puerto)
    http.serve_forever()


if __name__ == "__main__":
    main()

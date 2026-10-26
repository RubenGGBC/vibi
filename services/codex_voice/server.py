"""Run with python -m services.codex_voice.server. Local single-user service."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .backend import BackendError, DEFAULT_VOICE, VibiBackend, VOICES, validate_voice
from .rpc import CodexVoiceSession

WEB = Path(__file__).parent / 'web'


def request_authorized(headers, origin, token):
    return bool(
        headers.get('Host') == origin.removeprefix('http://')
        and headers.get('Origin', origin) == origin
        and secrets.compare_digest(headers.get('X-Voice-Token', ''), token)
        and re.fullmatch(r'[A-Za-z0-9-]{16,80}', headers.get('X-Voice-Client', ''))
    )


class VoiceService:
    def __init__(self, state_dir, backend_url='http://127.0.0.1:8000', session_factory=CodexVoiceSession):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.backend_url = backend_url
        VibiBackend(backend_url)  # Validate configuration before accepting requests.
        self.session_factory = session_factory
        self.clients = {}
        self.current = None
        self.owner = None
        self.lock = threading.RLock()

    def backend(self, owner):
        with self.lock:
            if owner not in self.clients:
                if len(self.clients) >= 32:
                    raise RuntimeError('Demasiadas pestañas. Reinicia el servicio para abrir otra sesión.')
                self.clients[owner] = VibiBackend(self.backend_url)
            return self.clients[owner]

    def start(self, owner, sdp, voice=DEFAULT_VOICE):
        validate_voice(voice)
        with self.lock:
            if self.current is not None:
                raise RuntimeError('Ya hay una llamada abierta. Desconéctala antes de cambiar de voz.')
            current = self.session_factory(self.state_dir, backend=self.backend(owner))
            self.current, self.owner = current, owner
        try:
            return current.start(sdp, voice)
        except Exception:
            self.stop(owner)
            raise

    def owned_session(self, owner):
        with self.lock:
            if owner != self.owner or self.current is None:
                raise RuntimeError('Esta pestaña no tiene una llamada abierta')
            return self.current

    def stop(self, owner):
        with self.lock:
            if self.owner != owner or self.current is None:
                return False
            current = self.current
            # Keep the slot occupied while shutting down, to prevent overlapping calls.
        current.close()
        with self.lock:
            if self.current is current:
                self.current = self.owner = None
        return True

    def shutdown(self):
        if self.owner is not None:
            self.stop(self.owner)
        for backend in self.clients.values():
            backend.logout()


def create_server(service, port=8768):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never write credentials, transcripts or SDP into HTTP access logs.

        @property
        def origin(self):
            return f'http://127.0.0.1:{self.server.server_port}'

        @property
        def owner(self):
            return self.headers.get('X-Voice-Client', '')

        def respond(self, value, status=200, content_type='application/json'):
            raw = value if isinstance(value, bytes) else (
                value.encode('utf-8') if isinstance(value, str) else json.dumps(value).encode())
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Permissions-Policy', 'microphone=(self)')
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.headers.get('Host') != self.origin.removeprefix('http://'):
                return self.respond({'error': 'Host no permitido'}, 403)
            path = self.path.split('?', 1)[0]
            if path == '/':
                html = (WEB / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', token)
                return self.respond(html, content_type='text/html')
            if path in ('/voice.js', '/voice.css', '/transcript.mjs'):
                return self.respond((WEB / path[1:]).read_bytes(), content_type=(
                    'text/javascript' if path.endswith(('.js', '.mjs')) else 'text/css'))
            if path == '/health':
                return self.respond({'ok': True})
            if not request_authorized(self.headers, self.origin, token):
                return self.respond({'error': 'Petición no autorizada'}, 403)
            if path == '/config':
                backend = service.backend(self.owner)
                return self.respond({'voices': list(VOICES), 'vibiConnected': backend.authenticated,
                                     'nombre': backend.name, 'backend': service.backend_url})
            if path == '/events':
                try:
                    current = service.owned_session(self.owner)
                except RuntimeError:
                    return self.respond({'active': False, 'events': []})
                return self.respond({'active': not current.closed, 'events': current.drain()})
            return self.respond({'error': 'No encontrado'}, 404)

        def do_POST(self):
            if not request_authorized(self.headers, self.origin, token):
                return self.respond({'error': 'Petición no autorizada'}, 403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= 100000:
                    return self.respond({'error': 'Petición demasiado grande'}, 413)
                data = json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(data, dict):
                    return self.respond({'error': 'Petición no válida'}, 400)
                if self.path == '/session':
                    sdp = data.get('sdp', '')
                    if not isinstance(sdp, str) or not sdp.startswith('v=0'):
                        return self.respond({'error': 'Oferta de audio no válida'}, 400)
                    return self.respond(service.start(self.owner, sdp, data.get('voice', DEFAULT_VOICE)))
                if self.path == '/stop':
                    service.stop(self.owner)
                    return self.respond({'ok': True})
                if self.path == '/login':
                    name, password = data.get('nombre'), data.get('password')
                    if not isinstance(name, str) or not isinstance(password, str) or not name or not password:
                        return self.respond({'error': 'Introduce usuario y contraseña'}, 400)
                    service.stop(self.owner)
                    return self.respond(service.backend(self.owner).login(name, password))
                if self.path == '/logout':
                    service.stop(self.owner)
                    service.backend(self.owner).logout()
                    return self.respond({'ok': True})
                if self.path == '/speak':
                    service.owned_session(self.owner).speak()
                    return self.respond({'ok': True})
                if self.path == '/text':
                    service.owned_session(self.owner).send_text(data.get('text'))
                    return self.respond({'ok': True})
                return self.respond({'error': 'No encontrado'}, 404)
            except (ValueError, json.JSONDecodeError) as error:
                return self.respond({'error': str(error)[:500]}, 400)
            except BackendError as error:
                return self.respond({'error': str(error)[:1000]}, error.status)
            except RuntimeError as error:
                return self.respond({'error': str(error)[:1000]}, 409)
            except Exception:
                return self.respond({'error': 'No se pudo completar la conexión. Comprueba que Codex y Vibi están disponibles.'}, 502)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    root = Path(__file__).resolve().parents[2]
    service = VoiceService(root / 'data' / 'codex-voice', os.getenv('VIBI_BACKEND_URL', 'http://127.0.0.1:8000'))
    port = int(os.getenv('VIBI_CODEX_VOICE_PORT', '8768'))
    server = create_server(service, port)
    stopped = threading.Event()

    def watchdog():
        while not stopped.wait(5):
            current = service.current
            if current and time.monotonic() - current.last_seen > 90:
                service.stop(service.owner)

    threading.Thread(target=watchdog, daemon=True).start()
    atexit.register(service.shutdown)
    print(f'Vibi Codex Voice: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        service.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()

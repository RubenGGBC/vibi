"""Authenticated calls to Vibi; preserves its existing execution policy."""
from __future__ import annotations

import json
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

VOICES = ('juniper', 'maple', 'breeze')
DEFAULT_VOICE = 'maple'


def validate_voice(voice: str) -> str:
    if voice not in VOICES:
        raise ValueError('Elige Juniper, Maple o Breeze')
    return voice


class BackendError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class VibiBackend:
    def __init__(self, base_url='http://127.0.0.1:8000', transport=None):
        url = urlsplit(base_url)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username
                or url.password or url.query or url.fragment or url.path not in ('', '/')):
            raise ValueError('VIBI_BACKEND_URL debe ser un origen HTTP(S), sin credenciales ni rutas')
        self.base_url = base_url.rstrip('/')
        self._token = None
        self.name = None
        self._transport = transport or self._http
        self._lock = threading.RLock()

    @property
    def authenticated(self):
        with self._lock:
            return bool(self._token)

    def _http(self, path, body, token, timeout):
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        raw = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            raw = json.dumps(body).encode()
        request = Request(self.base_url + path, data=raw, headers=headers)
        try:
            with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                payload = json.loads(error.read(8000))
                message = payload.get('error') or payload.get('detail') or 'Error de Vibi'
            except (ValueError, AttributeError):
                message = 'Vibi no pudo completar la petición'
            raise BackendError(str(message), error.code) from None
        except (URLError, TimeoutError):
            raise BackendError('No se pudo contactar con Vibi. No se ha reintentado la acción; comprueba su estado antes de repetirla.') from None

    def logout(self):
        with self._lock:
            self._token = None
            self.name = None

    def login(self, name, password):
        with self._lock:
            self.logout()
            try:
                result = self._transport('/api/auth/login', {'nombre': name, 'contraseña': password}, None, 30)
                token = result.get('token')
                if not isinstance(token, str) or not token:
                    raise BackendError('Vibi no devolvió una sesión válida')
                user = self._transport('/api/yo', None, token, 30)
                self._token = token
                self.name = user.get('nombre') or name
                return {'nombre': self.name}
            except Exception:
                self.logout()
                raise

    def request(self, text, call_id):
        if not isinstance(text, str) or not text.strip() or len(text) > 12000:
            raise BackendError('La petición debe contener entre 1 y 12000 caracteres', 400)
        with self._lock:
            token = self._token
        if not token:
            raise BackendError('Conecta tu cuenta de Vibi para usar sus herramientas', 401)
        try:
            return self._transport('/api/mensaje', {
                'texto': text.strip(), 'client_ref': f'voice-{call_id}',
            }, token, 600)
        except BackendError as error:
            if error.status == 401:
                self.logout()
            raise

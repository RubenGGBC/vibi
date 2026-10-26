import json
import unittest

from services.codex_voice.backend import BackendError, VibiBackend, validate_voice


class BackendTests(unittest.TestCase):
    def test_only_the_three_preview_voices_are_accepted(self):
        for voice in ('juniper', 'maple', 'breeze'):
            self.assertEqual(validate_voice(voice), voice)
        with self.assertRaises(ValueError):
            validate_voice('unknown')

    def test_login_keeps_token_in_backend_and_returns_only_public_identity(self):
        calls = []
        def transport(path, body, token, timeout):
            calls.append((path, body, token))
            return {'token': 'private-jwt'} if path.endswith('/login') else {'id': 'u1', 'nombre': 'Ruben'}
        backend = VibiBackend(transport=transport)
        self.assertEqual(backend.login('Ruben', 'secret'), {'nombre': 'Ruben'})
        self.assertNotIn('private-jwt', repr(backend))
        self.assertTrue(backend.authenticated)
        self.assertEqual(calls[1][2], 'private-jwt')

    def test_delegation_uses_existing_message_api_without_changing_provider(self):
        calls = []
        def transport(path, body, token, timeout):
            calls.append((path, body, token))
            if path.endswith('/login'): return {'token': 'jwt'}
            if path == '/api/yo': return {'nombre': 'Ruben'}
            return {'via': 'rapida', 'respuesta': 'Hay dos equipos conectados.'}
        backend = VibiBackend(transport=transport)
        backend.login('Ruben', 'secret')
        result = backend.request('¿Qué equipos tengo?', 'call-1')
        self.assertEqual(result['respuesta'], 'Hay dos equipos conectados.')
        path, body, token = calls[-1]
        self.assertEqual(path, '/api/mensaje')
        self.assertEqual(body['texto'], '¿Qué equipos tengo?')
        self.assertEqual(body['client_ref'], 'voice-call-1')
        self.assertEqual(token, 'jwt')
        self.assertFalse(any('config' in path for path, _, _ in calls))

    def test_requests_require_login(self):
        backend = VibiBackend(transport=lambda *args: self.fail('Should not contact backend'))
        with self.assertRaises(BackendError):
            backend.request('Abre una aplicación', 'call-2')

    def test_failed_login_removes_previous_session(self):
        def transport(path, body, token, timeout):
            if path.endswith('/login') and body['nombre'] == 'other': raise BackendError('No autorizado', 401)
            return {'token':'jwt'} if path.endswith('/login') else {'nombre':'Ruben'}
        backend = VibiBackend(transport=transport)
        backend.login('Ruben', 'secret')
        with self.assertRaises(BackendError): backend.login('other', 'wrong')
        self.assertFalse(backend.authenticated)

    def test_expired_login_is_cleared(self):
        def transport(path, body, token, timeout):
            if path == '/api/mensaje': raise BackendError('Sesión caducada', 401)
            return {'token':'jwt'} if path.endswith('/login') else {'nombre':'Ruben'}
        backend = VibiBackend(transport=transport)
        backend.login('Ruben', 'secret')
        with self.assertRaises(BackendError): backend.request('Hola', 'call-3')
        self.assertFalse(backend.authenticated)

    def test_tool_result_is_serializable_and_preserves_artifacts(self):
        def transport(path, body, token, timeout):
            if path.endswith('/login'): return {'token':'jwt'}
            if path == '/api/yo': return {'nombre':'Ruben'}
            return {'respuesta':'He preparado el archivo.', 'artifacts':[{'id':'file1'}]}
        backend = VibiBackend(transport=transport)
        backend.login('Ruben', 'secret')
        self.assertEqual(json.loads(json.dumps(backend.request('Prepara el archivo', 'c')))['artifacts'][0]['id'], 'file1')

    def test_backend_url_rejects_non_http_or_embedded_credentials(self):
        for url in ('file:///tmp', 'https://user:password@example.com', 'http://localhost:8000/path?secret=x'):
            with self.assertRaises(ValueError): VibiBackend(url)

if __name__ == '__main__': unittest.main()

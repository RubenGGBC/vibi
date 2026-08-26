import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import auth, db, perfil, perfil_entrevista, registro_mcp
from app.config import settings
from app.main import create_app


def _servidor(nombre: str, transporte: str = "remoto") -> registro_mcp.Servidor:
    return registro_mcp.Servidor(
        nombre, nombre.upper(), "desc", "1.0", "https://x", transporte, True
    )


class TestApiPerfil(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)

        self.patches = [
            patch.object(settings, 'db_path', str(root / 'vibi.db')),
            patch.object(
                settings, 'jwt_secret', 'secreto-de-pruebas-con-mas-de-32-bytes'
            ),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

        db.init_db()
        perfil.crear_tablas()
        self.user = db.get_or_create_user('testuser')
        db.set_password_hash(self.user['id'], auth.hash_password('password123'))

        self.client = TestClient(
            create_app(start_background=False, frontend_dir=root / 'missing-dist')
        )
        self.addCleanup(self.client.close)
        self.addCleanup(self.temp_dir.cleanup)

        token = self.client.post(
            '/api/auth/login',
            json={'nombre': 'testuser', 'contraseña': 'password123'},
        ).json()['token']
        self.headers = {'Authorization': f'Bearer {token}'}

    def test_obtener_perfil_vacio(self):
        res = self.client.get('/api/perfil', headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['user_id'], self.user['id'])
        self.assertEqual(data['afirmaciones'], [])
        self.assertEqual(data['capacidades'], [])
        self.assertEqual(data['metricas']['tasa_de_aceptacion'], 0.0)

    def test_crear_y_borrar_afirmacion(self):
        res = self.client.post(
            '/api/perfil/afirmaciones',
            headers=self.headers,
            json={'clase': 'dominio', 'valor': 'medicina', 'procedencia': 'entrevista'},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['valor'], 'medicina')
        self.assertEqual(data['clase'], 'dominio')

        res = self.client.get('/api/perfil', headers=self.headers)
        self.assertEqual(len(res.json()['afirmaciones']), 1)

        af_id = data['id']
        del_res = self.client.delete(f'/api/perfil/afirmaciones/{af_id}', headers=self.headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.json(), {'ok': True})

        res = self.client.get('/api/perfil', headers=self.headers)
        self.assertEqual(len(res.json()['afirmaciones']), 0)

    def test_aprobar_cambiar_nivel_y_borrar_capacidad(self):
        res = self.client.post(
            '/api/perfil/capacidades/aprobar',
            headers=self.headers,
            json={
                'tipo': 'mcp',
                'referencia': 'test/pdf',
                'justificacion': 'Lector de PDF',
                'transporte': 'remoto',
            },
        )
        self.assertEqual(res.status_code, 200)
        cap = res.json()
        self.assertEqual(cap['nivel'], 'completo')
        cap_id = cap['id']

        put_res = self.client.put(
            f'/api/perfil/capacidades/{cap_id}/nivel',
            headers=self.headers,
            json={'nivel': 'catalogo'},
        )
        self.assertEqual(put_res.status_code, 200)
        self.assertEqual(put_res.json()['nivel'], 'catalogo')

        del_res = self.client.delete(f'/api/perfil/capacidades/{cap_id}', headers=self.headers)
        self.assertEqual(del_res.status_code, 200)
        res = self.client.get('/api/perfil', headers=self.headers)
        self.assertEqual(len(res.json()['capacidades']), 0)

    def test_resetear_perfil(self):
        self.client.post(
            '/api/perfil/afirmaciones',
            headers=self.headers,
            json={'clase': 'dominio', 'valor': 'derecho', 'procedencia': 'entrevista'},
        )
        del_res = self.client.delete('/api/perfil', headers=self.headers)
        self.assertEqual(del_res.status_code, 200)
        res = self.client.get('/api/perfil', headers=self.headers)
        self.assertEqual(res.json()['afirmaciones'], [])

    def test_ejecutar_revision(self):
        res = self.client.post('/api/perfil/revision', headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('apoyadas', data)
        self.assertIn('decaidas', data)
        self.assertIn('propuestas_retirada', data)

    def test_entrevista_completar(self):
        body = {
            'afirmaciones': [
                {'clase': 'dominio', 'valor': 'medicina', 'procedencia': 'entrevista'},
                {'clase': 'herramienta', 'valor': 'pdf', 'procedencia': 'entrevista'},
            ],
            'capacidades': [
                {
                    'tipo': 'mcp',
                    'referencia': 'ai.pdfassistant/pdfassistant',
                    'justificacion': 'Lee apuntes',
                    'transporte': 'remoto',
                }
            ],
            'resumen': 'Se dedica a: medicina.',
        }
        res = self.client.post('/api/perfil/entrevista/completar', headers=self.headers, json=body)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data['afirmaciones']), 2)
        self.assertEqual(len(data['capacidades']), 1)
        self.assertEqual(data['resumen'], 'Se dedica a: medicina.')

    def test_entrevista_propuesta_deriva_terminos_del_texto_libre(self):
        """El servidor traduce el texto libre a términos, no el cliente.

        Sin `terminos_pedidos` explícitos, el endpoint debe apoyarse en lo que
        derive del texto libre para que aparezca el término «notes» — si esta
        lógica volviera a vivir solo en el frontend, este test no la vería.
        La derivación en sí (Groq, con el diccionario de respaldo) tiene sus
        propios tests en test_perfil_entrevista.py; aquí se dobla para no
        depender de la red real en cada corrida.
        """
        async def terminos_falsos(texto, cliente=None):
            return ['notes']

        def buscador(termino, limite=10):
            return {'notes': [_servidor('notes/notes-mcp')]}.get(termino, [])

        with patch.object(perfil_entrevista, 'terminos_de_texto_ia', terminos_falsos), \
                patch.object(registro_mcp, 'buscar', buscador), \
                patch.object(registro_mcp, 'verificar', lambda s: (True, '')):
            res = self.client.post(
                '/api/perfil/entrevista/propuesta',
                headers=self.headers,
                json={'texto_libre': 'Quiero que organice mis apuntes de clase'},
            )
        self.assertEqual(res.status_code, 200)
        referencias = [p['referencia'] for p in res.json()]
        self.assertIn('notes/notes-mcp', referencias)

    def test_entrevista_propuesta_sin_pistas_usa_respaldo_generico(self):
        """Sin términos explícitos ni pistas en el texto, cae a notes+pdf."""
        async def sin_terminos(texto, cliente=None):
            return []

        vistos = []

        def buscador(termino, limite=10):
            vistos.append(termino)
            return []

        with patch.object(perfil_entrevista, 'terminos_de_texto_ia', sin_terminos), \
                patch.object(registro_mcp, 'buscar', buscador), \
                patch.object(registro_mcp, 'verificar', lambda s: (True, '')):
            res = self.client.post(
                '/api/perfil/entrevista/propuesta',
                headers=self.headers,
                json={'texto_libre': 'Prefiero respuestas cortas'},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(set(vistos), {'notes', 'pdf', 'search'})

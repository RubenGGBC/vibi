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
        nombre, nombre.upper(), "desc", "1.0", "https://x", transporte, True,
        "https://mcp.example.test/endpoint" if transporte == "remoto" else "",
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
                'endpoint': 'https://mcp.example.test/pdf',
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
                    'endpoint': 'https://chat.pdfassistant.ai/mcp',
                }
            ],
            'resumen': 'Se dedica a: medicina.',
        }
        res = self.client.post('/api/perfil/entrevista/completar', headers=self.headers, json=body)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data['afirmaciones']), 2)
        self.assertEqual(len(data['capacidades']), 1)
        self.assertEqual(data['capacidades'][0]['endpoint'], 'https://chat.pdfassistant.ai/mcp')
        self.assertEqual(data['resumen'], 'Se dedica a: medicina.\nTrabaja con: pdf.')

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

    def test_las_aficiones_alimentan_el_bloque_de_lo_que_encaja(self):
        """Lo que la persona es, no solo lo que pide, tiene que buscarse.

        Hasta el 30/08/2026 solo se buscaba con las afirmaciones de clase
        «preferencia»: en la entrevista real de ese dia, contar que juega a
        videojuegos y escucha musica no genero ni una sola busqueda, y el
        bloque «encaja» llego vacio. Van por separado y no en el mismo saco
        porque son dos niveles de confianza distintos para quien lee.
        """
        async def terminos_falsos(texto, cliente=None):
            return ['games'] if 'videojuegos' in texto else ['notes']

        def buscador(termino, limite=10):
            return {
                'notes': [_servidor('notes/notes-mcp')],
                'games': [_servidor('juegos/games')],
            }.get(termino, [])

        with patch.object(perfil_entrevista, 'terminos_de_texto_ia', terminos_falsos), \
                patch.object(registro_mcp, 'buscar', buscador), \
                patch.object(registro_mcp, 'verificar', lambda s: (True, '')):
            res = self.client.post(
                '/api/perfil/entrevista/propuesta',
                headers=self.headers,
                json={
                    'texto_libre': 'Quiero que organice mis apuntes',
                    'texto_libre_adyacente': 'juego a videojuegos',
                },
            )

        self.assertEqual(res.status_code, 200)
        por_referencia = {p['referencia']: p['bloque'] for p in res.json()}
        self.assertEqual(por_referencia.get('notes/notes-mcp'), 'pedido')
        self.assertEqual(por_referencia.get('juegos/games'), 'encaja')

    def test_entrevista_turno_devuelve_lo_que_dice_perfil_entrevista(self):
        async def turno_falso(historial, cliente=None):
            assert historial == [{"rol": "vibi", "texto": "¿Para qué me vas a usar?"}]
            return {"vibi_dice": "¿Y qué esperas de ella?", "terminado": False}

        with patch.object(perfil_entrevista, 'turno_entrevista', turno_falso):
            res = self.client.post(
                '/api/perfil/entrevista/turno',
                headers=self.headers,
                json={'historial': [{'rol': 'vibi', 'texto': '¿Para qué me vas a usar?'}]},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {'vibi_dice': '¿Y qué esperas de ella?', 'terminado': False})

    def test_entrevista_voz_transcribe_sin_enrutar_al_motor_general(self):
        async def transcribir_falso(user_id, nombre, audio):
            return "Estudio medicina"

        with patch('app.executors.groq_speech.transcribir', transcribir_falso):
            res = self.client.post(
                '/api/perfil/entrevista/voz',
                headers=self.headers,
                files={'audio': ('voz.webm', b'contenido-de-audio', 'audio/webm')},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {'transcripcion': 'Estudio medicina'})

    def test_entrevista_voz_rechaza_formato_no_soportado(self):
        res = self.client.post(
            '/api/perfil/entrevista/voz',
            headers=self.headers,
            files={'audio': ('voz.txt', b'no es audio', 'text/plain')},
        )
        self.assertEqual(res.status_code, 415)

    def test_entrevista_propuesta_sin_pistas_usa_respaldo_generico(self):
        """Sin términos explícitos ni pistas en el texto, cae a notes+pdf.

        Sin adyacentes propios no hay bloque «encaja»: un término genérico de
        respaldo ahí («search») no encuentra nada relacionado con la persona,
        solo ruido de un registro público grande (probado en vivo).
        """
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
        self.assertEqual(set(vistos), {'notes', 'pdf'})

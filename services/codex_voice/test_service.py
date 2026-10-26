import tempfile
import unittest
from pathlib import Path

from services.codex_voice.server import VoiceService, request_authorized

class FakeSession:
    def __init__(self, cwd, backend=None):
        self.backend=backend; self.closed=False
    def start(self, sdp, voice): return {'sdp':'answer', 'voice':voice}
    def close(self): self.closed=True

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service=VoiceService(Path(self.temp.name), session_factory=FakeSession)
        self.addCleanup(self.service.shutdown)

    def test_voice_is_validated_before_creating_a_session(self):
        with self.assertRaises(ValueError): self.service.start('tab1','v=0','unknown')
        self.assertIsNone(self.service.current)

    def test_maple_is_the_default_voice(self):
        self.assertEqual(self.service.start('tab1','v=0')['voice'], 'maple')

    def test_other_tabs_cannot_close_active_voice(self):
        self.service.start('tab1','v=0','juniper')
        current=self.service.current
        self.assertFalse(self.service.stop('tab2'))
        self.assertIs(self.service.current,current)
        self.assertFalse(current.closed)
        self.assertTrue(self.service.stop('tab1'))
        self.assertTrue(current.closed)

    def test_busy_session_is_not_silently_replaced(self):
        self.service.start('tab1','v=0','maple')
        with self.assertRaises(RuntimeError): self.service.start('tab2','v=0','breeze')
        self.assertEqual(self.service.owner,'tab1')

    def test_origin_host_and_csrf_must_match(self):
        origin='http://127.0.0.1:8768'
        valid={'Host':'127.0.0.1:8768','Origin':origin,'X-Voice-Token':'token','X-Voice-Client':'a'*32}
        self.assertTrue(request_authorized(valid,origin,'token'))
        for key,value in [('Host','evil.test'),('Origin','https://evil.test'),('X-Voice-Token','wrong'),('X-Voice-Client','')]:
            with self.subTest(key=key):
                self.assertFalse(request_authorized({**valid,key:value},origin,'token'))

if __name__=='__main__': unittest.main()

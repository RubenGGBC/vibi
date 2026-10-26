import unittest
from services.codex_voice.rpc import CodexVoiceSession, tool_response, thread_options, realtime_options, safe_event


class RpcContracts(unittest.TestCase):
    def test_only_the_named_tool_is_dispatched(self):
        calls = []
        def handler(text, call_id):
            calls.append((text, call_id)); return {'respuesta': 'Disponible'}
        value = tool_response({'tool':'vibi_request','arguments':{'request':'Lista mis equipos'},'callId':'c1'}, handler)
        self.assertTrue(value['success'])
        self.assertIn('Disponible', value['contentItems'][0]['text'])
        self.assertEqual(calls, [('Lista mis equipos', 'c1')])
        self.assertFalse(tool_response({'tool':'shell','arguments':{}}, handler)['success'])
        self.assertEqual(len(calls), 1)

    def test_missing_tool_arguments_do_not_execute_anything(self):
        result = tool_response({'tool':'vibi_request','arguments':{}}, lambda *_: self.fail('Unexpected call'))
        self.assertFalse(result['success'])

    def test_backend_failures_are_reported_without_retry(self):
        calls = []
        def fail(*args):
            calls.append(args); raise RuntimeError('Sesión caducada')
        result = tool_response({'tool':'vibi_request','arguments':{'request':'Hola'},'callId':'c'}, fail)
        self.assertFalse(result['success'])
        self.assertEqual(len(calls),1)
        self.assertIn('caducada',result['contentItems'][0]['text'])

    def test_preview_does_not_advertise_vibi_tools(self):
        result = thread_options('/empty', False)
        self.assertEqual(result['dynamicTools'], [])
        self.assertTrue(result['ephemeral'])
        self.assertEqual(result['sandbox'], 'read-only')

    def test_connected_mode_advertises_vibi_bridge(self):
        result = thread_options('/empty', True)
        self.assertEqual(result['dynamicTools'][0]['name'], 'vibi_request')
        self.assertIn('Antigravity', result['baseInstructions'])

    def test_voice_selection_is_explicit_and_webrtc(self):
        for voice in ('juniper','maple','breeze'):
            result = realtime_options('thread1','v=0',voice)
            self.assertEqual(result['voice'],voice)
            self.assertEqual(result['transport']['type'],'webrtc')
            self.assertFalse(result['clientManagedHandoffs'])
        with self.assertRaises(ValueError): realtime_options('thread1','v=0','cove')

    def test_events_do_not_expose_credentials_sdp_or_arbitrary_parameters(self):
        value = safe_event('thread/realtime/started', {'token':'secret','sdp':'private','threadId':'t','version':'v3'})
        self.assertEqual(value,{'type':'thread/realtime/started'})
        self.assertNotIn('secret',str(value))

    def test_typed_request_starts_work_instead_of_only_appending_quiet_voice_context(self):
        session = CodexVoiceSession.__new__(CodexVoiceSession)
        session.thread_id = 'thread1'
        calls = []
        session.call = lambda method, params: calls.append((method,params))
        session.send_text('Consulta mis equipos')
        self.assertEqual(calls[0][0], 'turn/start')
        self.assertEqual(calls[0][1]['input'], [{'type':'text','text':'Consulta mis equipos'}])

if __name__ == '__main__': unittest.main()

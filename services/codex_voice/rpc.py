"""Codex app-server stdio client. Credentials stay in Codex's own store."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from .backend import DEFAULT_VOICE, validate_voice

INSTRUCTIONS = '''Eres Vibi, una asistente personal. Responde en español, de forma breve y natural.
Para cualquier petición sobre dispositivos, archivos, skills, trabajo o programación, usa vibi_request.
Vibi ejecuta esas peticiones con su motor configurado, incluido Antigravity. No programes tú ni cambies motores.
No uses terminal, archivos locales, navegador ni herramientas distintas de vibi_request.
No anuncies éxito hasta recibir el resultado. Si hay una aprobación pendiente, explícalo sin aprobar por el usuario.
Al recibir un resultado de Vibi, comunícalo por voz sin inventar acciones ni resultados.
La conversación informal puedes resolverla directamente. No prometas que una interrupción de voz cancela una tarea ya enviada.'''


def thread_options(cwd, connected):
    tools = [{
        'type': 'function', 'name': 'vibi_request',
        'description': 'Envía la petición del usuario a su Vibi real. Vibi gestiona equipos, archivos, skills y programación con sus motores existentes. Conserva sus permisos y autorizaciones.',
        'inputSchema': {'type': 'object', 'properties': {'request': {'type': 'string'}},
                        'required': ['request'], 'additionalProperties': False},
    }] if connected else []
    return {
        'cwd': str(cwd), 'ephemeral': True, 'sandbox': 'read-only', 'approvalPolicy': 'never',
        'baseInstructions': INSTRUCTIONS if connected else
            'Eres Vibi, una asistente personal. Conversa en español con naturalidad. Esta es una prueba de voz: no tienes acceso a dispositivos ni herramientas de Vibi.',
        'dynamicTools': tools,
        'config': {'mcp_servers': {}, 'features': {'shell_tool': False, 'plugins': False, 'remote_plugin': False}},
    }


def realtime_options(thread_id, sdp, voice):
    return {
        'threadId': thread_id, 'outputModality': 'audio', 'voice': validate_voice(voice),
        'includeStartupContext': True, 'clientManagedHandoffs': False, 'version': 'v3',
        'transport': {'type': 'webrtc', 'sdp': sdp},
    }


def tool_response(params, handler):
    request = params.get('arguments')
    if (params.get('tool') != 'vibi_request' or not isinstance(request, dict)
            or not isinstance(request.get('request'), str) or not request['request'].strip()):
        return {'success': False, 'contentItems': [{'type': 'inputText', 'text': 'Herramienta o argumentos no válidos'}]}
    try:
        result = handler(request['request'], params.get('callId', 'unknown'))
        return {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(result, ensure_ascii=False)}]}
    except Exception as error:
        return {'success': False, 'contentItems': [{'type': 'inputText', 'text': str(error)[:2000]}]}


def safe_event(method, params):
    result = {'type': method}
    for key in ('message', 'reason', 'text', 'delta'):
        if isinstance(params.get(key), str):
            result[key] = params[key][:3000]
    return result


class CodexVoiceSession:
    def __init__(self, cwd: Path, backend=None, executable=None):
        binary = executable or shutil.which('codex')
        if not binary:
            raise RuntimeError('No se encontró Codex CLI. Instálalo e inicia sesión con ChatGPT.')
        env = os.environ.copy()
        for name in ('OPENAI_API_KEY', 'CODEX_API_KEY'):
            env.pop(name, None)
        self.process = subprocess.Popen(
            [binary, 'app-server', '--listen', 'stdio://', '--disable', 'shell_tool',
             '--disable', 'plugins', '--disable', 'remote_plugin'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        self.cwd = cwd
        self.backend = backend
        self.pending = {}
        self.events = []
        self.counter = 0
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.answer = queue.Queue(maxsize=1)
        self.thread_id = None
        self.closed = False
        self.stopping = threading.Event()
        self.last_seen = time.monotonic()
        self.tool_lock = threading.Lock()
        self.tool_results = {}
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def emit(self, event):
        with self.lock:
            self.events.append(event)
            self.events = self.events[-150:]

    def drain(self):
        self.last_seen = time.monotonic()
        with self.lock:
            events, self.events = self.events, []
        return events

    def write(self, message):
        with self.write_lock:
            if self.closed or self.process.poll() is not None:
                raise RuntimeError('La sesión de Codex está cerrada')
            self.process.stdin.write(json.dumps(message) + '\n')
            self.process.stdin.flush()

    def call(self, method, params, timeout=55):
        with self.lock:
            self.counter += 1
            identifier = self.counter
            target = self.pending[identifier] = queue.Queue(maxsize=1)
        try:
            self.write({'id': identifier, 'method': method, 'params': params})
            try:
                response = target.get(timeout=timeout)
            except queue.Empty:
                raise RuntimeError(f'Codex no respondió a tiempo ({method})') from None
            if 'error' in response:
                raise RuntimeError(response['error'].get('message', 'Error de Codex'))
            return response.get('result', {})
        finally:
            with self.lock:
                self.pending.pop(identifier, None)

    def _tool(self, message):
        with self.tool_lock:
            params = message.get('params', {})
            call_id = params.get('callId')
            if call_id and call_id in self.tool_results:
                result = self.tool_results[call_id]
            elif self.backend is None or self.stopping.is_set():
                result = {'success': False, 'contentItems': [{'type': 'inputText', 'text': 'Vibi no está conectada o la sesión ha terminado'}]}
            else:
                self.emit({'type': 'vibi/request', 'text': str(params.get('arguments', {}).get('request', ''))[:2000]})
                result = tool_response(params, self.backend.request)
                if call_id:
                    self.tool_results[call_id] = result
                self.emit({'type': 'vibi/result', 'success': result['success'], 'text': result['contentItems'][0]['text'][:3000]})
            try:
                self.write({'id': message['id'], 'result': result})
            except (RuntimeError, OSError):
                pass

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if 'id' in message and ('result' in message or 'error' in message):
                    with self.lock:
                        target = self.pending.get(message['id'])
                    if target:
                        target.put_nowait(message)
                    continue
                method = message.get('method', '')
                params = message.get('params', {})
                if 'id' in message:
                    if method == 'item/tool/call':
                        threading.Thread(target=self._tool, args=(message,), daemon=True).start()
                    else:
                        self.write({'id': message['id'], 'error': {'code': -32601, 'message': 'Usa las herramientas y aprobaciones de Vibi'}})
                    continue
                if method == 'thread/realtime/sdp':
                    try:
                        self.answer.put_nowait({'sdp': params['sdp']})
                    except queue.Full:
                        pass
                if method == 'thread/realtime/error':
                    try:
                        self.answer.put_nowait({'error': params.get('message', 'Error de voz')})
                    except queue.Full:
                        pass
                if method.startswith('thread/realtime/') or method in ('turn/started', 'turn/completed'):
                    self.emit(safe_event(method, params))
        finally:
            self.emit({'type': 'process/closed'})
            with self.lock:
                for target in self.pending.values():
                    try:
                        target.put_nowait({'error': {'message': 'Se cerró el proceso de Codex'}})
                    except queue.Full:
                        pass

    def start(self, sdp, voice=DEFAULT_VOICE):
        validate_voice(voice)
        self.call('initialize', {
            'clientInfo': {'name': 'vibi_voice', 'title': 'Vibi Voice', 'version': '0.1.0'},
            'capabilities': {'experimentalApi': True},
        })
        self.write({'method': 'initialized'})
        account = self.call('account/read', {'refreshToken': False}).get('account') or {}
        if account.get('type') != 'chatgpt':
            raise RuntimeError('Inicia sesión en Codex CLI con ChatGPT')
        connected = bool(self.backend and self.backend.authenticated)
        result = self.call('thread/start', thread_options(self.cwd, connected))
        self.thread_id = result['thread']['id']
        self.call('thread/realtime/start', realtime_options(self.thread_id, sdp, voice))
        try:
            answer = self.answer.get(timeout=55)
        except queue.Empty:
            raise RuntimeError('No llegó la negociación de voz') from None
        if 'error' in answer:
            raise RuntimeError(answer['error'])
        self.last_seen = time.monotonic()
        return {**answer, 'voice': voice, 'vibiConnected': connected}

    def speak(self):
        return self.call('thread/realtime/appendSpeech', {
            'threadId': self.thread_id,
            'text': 'Hola, soy Vibi. Podemos charlar un rato para que escuches mi voz. Cuéntame, ¿qué te apetece hacer hoy?',
        })

    def send_text(self, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 12000:
            raise ValueError('Escribe una petición de entre 1 y 12000 caracteres')
        return self.call('turn/start', {
            'threadId': self.thread_id,
            'input': [{'type': 'text', 'text': text}],
        })

    def close(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        try:
            if self.thread_id and self.process.poll() is None:
                self.call('thread/realtime/stop', {'threadId': self.thread_id}, timeout=4)
        except Exception:
            pass
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=4)

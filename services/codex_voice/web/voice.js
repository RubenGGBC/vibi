import { TranscriptAssembler } from './transcript.mjs';
const $ = selector => document.querySelector(selector);
const token = $('meta[name="voice-token"]').content;
const owner = sessionStorage.getItem('vibi.voice.client') || crypto.randomUUID();
sessionStorage.setItem('vibi.voice.client', owner);
const voices = { juniper: 'Juniper', maple: 'Maple', breeze: 'Breeze' };
let voice = localStorage.getItem('vibi.voice.preferred') || 'maple';
if (!voices[voice]) voice = 'maple';
let pc, stream, channel, poll, statsTimer, context, raf, controller;
let running = false, connecting = false, vibiConnected = false, startedAt = 0;
let transcript = new TranscriptAssembler();
const diagnostics = { voice, connected: false, dataChannel: false, receivedAudioBytes: 0, audioPackets: 0, events: [] };
window.voiceDiagnostics = diagnostics;

function log(text) {
  $('#log').textContent = (new Date().toLocaleTimeString() + ' ' + text + '\n' + $('#log').textContent).slice(0, 7000);
  diagnostics.events.push(text);
  diagnostics.events = diagnostics.events.slice(-40);
}
function status(text, live = false) {
  $('#status').textContent = text;
  $('#dot').classList.toggle('live', live);
}
async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'X-Voice-Token': token, 'X-Voice-Client': owner, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: path === '/session' ? controller?.signal : undefined,
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'No se pudo completar la petición');
  return result;
}
function addText(role, text, key) {
  if (!text) return;
  let line = key ? [...$('#transcript').children].find(node => node.dataset.key === key) : null;
  if (!line) {
    line = document.createElement('p');
    if (key) line.dataset.key = key;
    line.className = role === 'request' ? 'request' : '';
    $('#transcript').append(line);
  }
  line.textContent = (role === 'user' ? 'Tú: ' : role === 'request' ? 'Vibi: ' : '') + text;
  while ($('#transcript').children.length > 35) $('#transcript').firstElementChild.remove();
  line.scrollIntoView({ block: 'nearest' });
}
function dataEvent(event) {
  try {
    const message = JSON.parse(event.data);
    const type = message.type || 'evento';
    log(type);
    if (type.includes('speech_started')) status('Te escucho…', true);
    if (type.includes('speech_stopped')) status('Preparando respuesta…', true);
    if (type === 'error') $('#error').textContent = message.error?.message || 'Error de audio';
    const assembled = transcript.push(message);
    if (assembled) addText(assembled.role, assembled.text, assembled.key);
    const text = message.transcript || message.text;
    if (!assembled && !type.endsWith('_transcript.added') && type.includes('transcript') && typeof text === 'string') {
      addText(type.startsWith('input') || type.includes('input_audio') ? 'user' : 'assistant', text,
        message.item_id || message.item?.id || message.id);
    }
  } catch { log('Mensaje de audio recibido'); }
}
function release() {
  running = connecting = false;
  controller?.abort();
  clearTimeout(poll); clearInterval(statsTimer); cancelAnimationFrame(raf);
  stream?.getTracks().forEach(track => track.stop()); stream = null;
  pc?.close(); pc = null; channel = null;
  context?.close().catch(() => {}); context = null;
  $('#audio').srcObject = null; $('#level').style.width = '0';
  $('#connect').disabled = false;
  for (const id of ['stop', 'greet', 'mute', 'text', 'send']) $('#' + id).disabled = true;
  $('#mute').textContent = 'Silenciar micro';
  diagnostics.connected = diagnostics.dataChannel = false;
  status(voices[voice] + ' seleccionada');
}
async function stop() {
  release();
  try { await api('/stop', {}); } catch (error) { log(error.message); }
}
async function pollEvents() {
  if (!running) return;
  try {
    const result = await api('/events');
    if (!result.active) { await stop(); return; }
    for (const event of result.events) {
      log(event.type);
      if (event.type.endsWith('/error')) {
        $('#error').textContent = event.message || 'Error de voz'; await stop(); return;
      }
      if (event.type.endsWith('/closed') || event.type === 'process/closed') { await stop(); return; }
      if (event.type === 'vibi/request') addText('request', 'Consultando tu Vibi: ' + event.text);
      if (event.type === 'vibi/result') {
        let result; try { result = JSON.parse(event.text); } catch { result = { respuesta: event.text }; }
        addText('request', result.respuesta || (result.task_id ? 'Trabajo enviado: ' + result.task_id : event.text));
      }
    }
  } catch (error) { log(error.message); }
  if (running) poll = setTimeout(pollEvents, 1200);
}
function meter() {
  if (!context || !stream) return;
  const source = context.createMediaStreamSource(stream), analyser = context.createAnalyser();
  source.connect(analyser); analyser.fftSize = 256;
  const values = new Uint8Array(analyser.fftSize);
  function tick() {
    analyser.getByteTimeDomainData(values);
    const energy = Math.sqrt(values.reduce((sum, v) => sum + ((v - 128) / 128) ** 2, 0) / values.length);
    $('#level').style.width = Math.min(100, energy * 450) + '%';
    raf = requestAnimationFrame(tick);
  }
  tick();
}
async function connect() {
  if (running || connecting) return;
  connecting = true; controller = new AbortController();
  transcript = new TranscriptAssembler();
  $('#transcript').replaceChildren();
  Object.assign(diagnostics, { voice, connected: false, dataChannel: false, receivedAudioBytes: 0, audioPackets: 0, events: [] });
  $('#error').textContent = ''; $('#connect').disabled = true; $('#stop').disabled = false;
  status('Solicitando micrófono…');
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    if (!connecting) { stream.getTracks().forEach(track => track.stop()); return; }
    context = new AudioContext(); await context.resume(); meter();
    pc = new RTCPeerConnection(); stream.getTracks().forEach(track => pc.addTrack(track, stream));
    pc.ontrack = event => {
      $('#audio').srcObject = event.streams[0] || new MediaStream([event.track]);
      $('#audio').play().catch(() => { $('#error').textContent = 'Pulsa «Escuchar un saludo» para habilitar el altavoz.'; });
      log('Pista de audio recibida');
    };
    pc.onconnectionstatechange = () => {
      if (!pc) return;
      log('WebRTC: ' + pc.connectionState);
      if (pc.connectionState === 'connected') { diagnostics.connected = true; status(voices[voice] + ' · Te escucho', true); }
      if (pc.connectionState === 'failed') { $('#error').textContent = 'Falló la conexión de audio. Vuelve a conectar.'; stop(); }
    };
    channel = pc.createDataChannel('oai-events');
    channel.onopen = () => { diagnostics.dataChannel = true; log('Canal de datos abierto'); };
    channel.onmessage = dataEvent;
    await pc.setLocalDescription(await pc.createOffer());
    status('Conectando ' + voices[voice] + '…');
    const answer = await api('/session', { sdp: pc.localDescription.sdp, voice });
    if (!connecting) return;
    await pc.setRemoteDescription({ type: 'answer', sdp: answer.sdp });
    running = true; connecting = false; startedAt = Date.now();
    for (const id of ['greet', 'mute', 'text', 'send']) $('#' + id).disabled = false;
    pollEvents();
    statsTimer = setInterval(async () => {
      $('#duration').textContent = Math.floor((Date.now() - startedAt) / 60000) + ':' + String(Math.floor((Date.now() - startedAt) / 1000) % 60).padStart(2, '0');
      if (!pc) return;
      try {
        const stats = await pc.getStats();
        stats.forEach(row => {
          if (row.type === 'inbound-rtp' && row.kind === 'audio') {
            diagnostics.receivedAudioBytes = row.bytesReceived || 0;
            diagnostics.audioPackets = row.packetsReceived || 0;
            $('#stats').textContent = 'Audio recibido: ' + diagnostics.receivedAudioBytes + ' bytes · ' + diagnostics.audioPackets + ' paquetes';
          }
        });
      } catch { /* Closing the peer can interrupt getStats. */ }
    }, 1000);
  } catch (error) {
    const message = error.name === 'NotAllowedError' ? 'Permite el micrófono para conversar.' : error.message;
    await stop(); $('#error').textContent = message; log(message);
  }
}
async function chooseVoice(next) {
  if (!voices[next]) return;
  if (running || connecting) await stop();
  voice = next; diagnostics.voice = next; localStorage.setItem('vibi.voice.preferred', next);
  document.querySelectorAll('[data-voice]').forEach(button => {
    button.classList.toggle('selected', button.dataset.voice === voice);
    button.setAttribute('aria-pressed', String(button.dataset.voice === voice));
  });
  $('#connect').textContent = 'Conversar con ' + voices[voice];
  status(voices[voice] + ' seleccionada');
}
async function refreshAccount() {
  try {
    const config = await api('/config'); vibiConnected = config.vibiConnected;
    $('#mode').textContent = vibiConnected ? 'Conectada a Vibi' : 'Prueba de voces';
    $('#account-button').textContent = vibiConnected ? 'Cerrar sesión' : 'Conectar cuenta';
    $('#account-status').textContent = vibiConnected ? 'Sesión de ' + config.nombre + '. Tus peticiones se enviarán al motor actual de Vibi.' : 'Puedes probar las voces sin iniciar sesión. Conecta Vibi para usar tus dispositivos y skills.';
  } catch (error) { $('#error').textContent = error.message; }
}
$('#connect').onclick = connect; $('#stop').onclick = stop;
document.querySelectorAll('[data-voice]').forEach(button => button.onclick = () => chooseVoice(button.dataset.voice));
$('#greet').onclick = async () => { try { await $('#audio').play(); await api('/speak', {}); log('Saludo solicitado'); } catch (error) { $('#error').textContent = error.message; } };
$('#mute').onclick = () => {
  const tracks = stream?.getAudioTracks() || [], enabled = !tracks[0]?.enabled;
  tracks.forEach(track => { track.enabled = enabled; }); $('#mute').textContent = enabled ? 'Silenciar micro' : 'Activar micro';
};
$('#text-form').onsubmit = async event => {
  event.preventDefault(); const input = $('#text'), text = input.value.trim(); if (!text) return;
  try { await api('/text', { text }); addText('user', text); input.value = ''; } catch (error) { $('#error').textContent = error.message; }
};
$('#account-button').onclick = async () => {
  if (vibiConnected) { await stop(); await api('/logout', {}); await refreshAccount(); }
  else $('#login-dialog').showModal();
};
$('#login-cancel').onclick = () => $('#login-dialog').close();
$('#login').onsubmit = async event => {
  event.preventDefault(); $('#login-submit').disabled = true; $('#login-error').textContent = '';
  const form = new FormData(event.target);
  try {
    await stop(); await api('/login', { nombre: form.get('nombre'), password: form.get('password') });
    event.target.reset(); $('#login-dialog').close(); await refreshAccount();
  } catch (error) { $('#login-error').textContent = error.message; }
  finally { $('#login-submit').disabled = false; }
};
window.addEventListener('pagehide', () => {
  release(); fetch('/stop', { method: 'POST', headers: { 'X-Voice-Token': token, 'X-Voice-Client': owner, 'Content-Type': 'application/json' }, body: '{}', keepalive: true }).catch(() => {});
});
chooseVoice(voice); refreshAccount();

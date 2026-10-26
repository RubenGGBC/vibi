# Voz de Codex en Vibi: investigación y prueba local

Fecha: 26 de octubre de 2026. Alcance: comprobar viabilidad técnica; no integrar todavía el producto.

## Resultado

La instalación local de Codex **aceptó la negociación de una sesión de voz WebRTC usando su sesión de ChatGPT**, sin aportar una clave de API. Esto justifica un prototipo de conversación completa. No demuestra todavía transmisión efectiva de audio, calidad, latencia, interrupciones ni disponibilidad general para otras cuentas.

El experimento no capturó el micrófono, no envió voz, no reprodujo audio y no inició turnos del agente. Los procesos de diagnóstico finalizaron al terminar. No se modificó la configuración de Codex ni el código funcional de Vibi.

## Evidencia local

- Binario: `C:/Users/rebel/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe`.
- Versión: `codex-cli 0.164.0`.
- `codex login status`: sesión mediante ChatGPT.
- Los esquemas generados por ese binario contienen `thread/realtime/start`, `appendAudio`, `appendText`, `appendSpeech`, `stop` y `listVoices`.
- Canal de control del diagnóstico: JSON por stdin/stdout, con `experimentalApi: true` y nombre de cliente propio `vibi_voice_research`. No se suplantó al cliente oficial.
- Conversación efímera, sandbox de solo lectura, sin solicitudes de herramientas. Se deshabilitó la inclusión del contexto de arranque en el inicio de voz.
- Se retiraron `OPENAI_API_KEY` y `CODEX_API_KEY` del entorno del proceso de diagnóstico. No se extrajeron ni imprimieron credenciales.

| Prueba | Resultado observado |
|---|---|
| Inicializar app-server | Correcto |
| `account/read` | Tipo `chatgpt`, sesión presente |
| `thread/realtime/listVoices` | Correcto, respuesta con catálogo |
| Inicio de voz con transporte WebSocket | Notificación de error: requiere autenticación con clave de API |
| Inicio de voz con transporte WebRTC y versión `v3` | Notificación `thread/realtime/started` |
| Respuesta SDP del servidor | `thread/realtime/sdp`, 1690 caracteres |
| Detener sesión | Solicitud aceptada |

Un resultado vacío de `thread/realtime/start` no basta para declarar éxito: el intento WebSocket fue aceptado inicialmente y falló después por notificación. En WebRTC se esperaron las notificaciones de inicio y SDP.

La oferta SDP se generó con `RTCPeerConnection`, una transceiver de audio y un canal de datos en Edge headless con perfil temporal. No se solicitó `getUserMedia`. El navegador se cerró antes de la prueba del servidor; por eso **no se comprobó ICE/DTLS ni audio de extremo a extremo**.

Los scripts, esquemas y SDP del diagnóstico están en `data/.voice-research/`, ignorado por Git. No publicar el perfil temporal ni las trazas sin revisión.

## Lo que explica el código oficial

El protocolo expone audio, transcripciones y WebRTC como funciones experimentales. [Tipos del protocolo](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/v2/realtime.rs).

En el código examinado, WebSocket busca una clave de API; WebRTC crea la llamada mediante el cliente de modelos y conserva la autenticación para el canal de control. Esto concuerda con los dos resultados locales. [Gestión de la conversación](https://github.com/openai/codex/blob/main/codex-rs/core/src/realtime_conversation.rs), [creación de llamadas](https://github.com/openai/codex/blob/main/codex-rs/core/src/client.rs).

La presencia de código y una negociación aceptada no prueban un contrato estable ni el derecho de cualquier cuenta a usarlo. El modo app-server tiene superficies experimentales y la autenticación para una aplicación local debe distinguirse de un servicio alojado o comercial. No se ha determinado coste, cuota o facturación de esta ruta de voz. [App-server y autenticación](https://learn.chatgpt.com/docs/app-server), [Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server).

## Claude y la voz actual de Vibi

Anthropic documenta `/voice` con pulsación de la barra espaciadora. Su ayuda distingue dictado en Claude Code de conversación bidireccional. No se localizó una interfaz pública del Agent SDK que exponga ese sistema de voz para Vibi. Esto no prueba que sea imposible, pero no hay una integración validada. [Consejos del CLI](https://support.claude.com/en/articles/14554000-claude-code-power-user-tips), [modo de voz](https://support.claude.com/en/articles/11101966-use-voice-mode).

En el código actual de Vibi la cadena web no es enteramente local: `app/executors/groq_speech.py` envía clips a Groq para transcribir; `app/executors/edge_speech.py` obtiene síntesis mediante edge-tts. `frontend/src/lib/voice.ts` detecta silencios de 800 ms, graba clips y contempla síntesis del navegador. Por tanto, conviene medir la cadena completa y no atribuir la espera solo a modelos locales.

## Siguiente experimento recomendado

Prototipo aislado con el navegador manteniendo el peer WebRTC abierto: enviar oferta al puente local de app-server, aplicar la respuesta SDP y comprobar audio en ambos sentidos. Después medir interrupción al hablar, demora hasta el primer audio, reconexión y cierre. No reemplazar la voz actual hasta contar con estos resultados.

Para conservar la identidad de Vibi, separar voz y ejecución: una petición hablada debe pasar por las autorizaciones y herramientas de Vibi. No dar acceso general al agente de código como sustituto de esos permisos. El protocolo ofrece handoffs gestionados por el cliente y entrada de texto para explorar ese puente, pero la integración con el motor actual de Vibi sigue pendiente.

## Prueba interactiva posterior

Se preparó una página temporal en `http://127.0.0.1:8767`, servida por `data/.voice-research/voice_server.py`, con controles de conexión, mute, frase de prueba y desconexión. Usa un proceso independiente de app-server y una conversación efímera. No sustituye la voz de Vibi.

Una prueba de navegador con micrófono sintético confirmó conexión WebRTC, canal de datos abierto, pista remota y **2990 bytes / 58 paquetes de audio entrante** después de solicitar una frase mediante `appendSpeech`. No se capturó el micrófono real. Este resultado confirma transporte efectivo de audio de salida, no solo SDP. Quedan por validar conversación con voz humana, interrupciones y latencia percibida.

El servidor escucha únicamente en loopback. Las operaciones usan un token temporal de la página y verifican origen. Se detiene la sesión al desconectar o tras ausencia prolongada del cliente. Los scripts son un experimento desechable dentro de `data`, no una integración de producción ni parte del frontend publicado.

## Servicio con selector y puente a Vibi

La implementación mantenible está en `services/codex_voice`, separada del experimento inicial. Escucha por defecto en `http://127.0.0.1:8768`, ofrece Juniper, Maple y Breeze y permite iniciar sesión en el backend de Vibi. Usa una herramienta dinámica de Codex para enviar `/api/mensaje` al motor existente; no cambia proveedores ni preferencias de programación. El acceso se ha añadido a la cabecera de `Frontend TFG`.

Verificaciones: 21 pruebas Python, 3 de transcripciones y 40 de frontend; compilación del frontend correcta. Cada voz produjo audio con micrófono sintético. Se comprobó el recorrido página → turno Codex → herramienta → backend Vibi simulado → resultado → audio, con una única llamada al backend de prueba. Una conversación autenticada con el Vibi real requiere que el usuario inicie sesión en el selector. El usuario ha elegido Maple como voz predeterminada; se documentó el arranque para macOS, pendiente de prueba en un Mac físico.

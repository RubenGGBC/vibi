# Morgana TTS neuronal: diseño de síntesis de voz sin coste

## Objetivo

Sustituir la locución robótica de `window.speechSynthesis` por voces neuronales, sin introducir coste recurrente y sin que Morgana se quede muda si el servicio falla.

Hoy `speakSpanish` (`frontend/src/lib/voice.ts`) delega en la síntesis del navegador. La calidad depende de las voces instaladas en el sistema operativo del dispositivo: en un equipo sin voces españolas, `selectSpanishVoice` devuelve `undefined` y Morgana habla con la voz por defecto, en el idioma que toque. El resultado es inconsistente y suena a máquina.

## Decisiones

- La síntesis se hará con **edge-tts**, que expone las voces neuronales del servicio de lectura en voz alta de Microsoft Edge. Es gratuito, sin API key y sin cuota documentada.
- `window.speechSynthesis` **se conserva como fallback**. Nunca se elimina: si edge-tts falla, está bloqueado o no hay red, Morgana sigue hablando con la voz del navegador.
- La respuesta se trocea **por frases** y se reproduce encadenada. Morgana empieza a hablar en cuanto llega el primer fragmento, en lugar de esperar a que se sintetice la respuesta completa.
- El troceo lo hace el **frontend**; el backend recibe texto suelto y devuelve un MP3. El backend no sabe nada de frases, de orden ni de reproducción.
- La síntesis **no se integra en el sistema de lanes** de `ai_providers.py`. `resolve_lane` resuelve "qué proveedor y qué API key tiene este usuario", y edge-tts no tiene key ni proveedor alternativo que elegir: pasar por ahí solo produciría `ProviderConfigurationError`. Si en el futuro se añade un TTS de pago, entonces tendrá sentido promoverlo a lane.
- La voz se configura por `.env`, siguiendo el "nada hardcodeado" de `app/config.py`. No se añade UI en Ajustes: es una preferencia que se toca una vez.
- No se cachea audio en disco. Introduciría estado en servidor (dónde vive, cuándo se borra) para un problema que todavía no existe.

### Alternativas descartadas

- **Google Cloud TTS.** Chirp 3 HD suena excelente y regala 1 M de caracteres al mes, pero exige activar facturación y una service account. Las voces Standard, con 4 M gratis, suenan igual que lo que ya hay.
- **Kokoro-82M local.** Gratis y offline para siempre, pero cuesta ~350 MB de modelo y una dependencia de runtime a cambio de una voz algo menos expresiva que la de Microsoft.
- **OpenAI, ElevenLabs, Groq PlayAI.** Todos de pago por uso, descartados por la restricción de coste cero.

El riesgo asumido de edge-tts es que consume un endpoint no oficial: puede cambiar o limitar el tráfico sin aviso. El fallback a `speechSynthesis` es precisamente la mitigación de ese riesgo.

## Arquitectura y responsabilidades

### Backend

**`app/executors/edge_speech.py`** (nuevo, simétrico a `groq_speech.py`). Una única función pública:

```python
async def sintetizar(texto: str, *, voz: str | None = None) -> bytes
```

Envuelve `edge_tts.Communicate(...).stream()` acumulando los eventos de audio y devuelve un MP3. No conoce HTTP, ni usuarios, ni el troceo. Se prueba sustituyendo `Communicate`, sin red.

Se llama `edge_speech` y no `edge_tts` para no confundirse con el paquete de terceros del mismo nombre.

**`POST /api/tts`** en `app/api.py`. Autenticado con `Depends(auth.current_user)`, como el resto de la API. Recibe `{"texto": "..."}` y devuelve `Response(media_type="audio/mpeg")`. Sin estado. Códigos de error:

| Situación | Código | Detalle |
|---|---|---|
| `tts_enabled` desactivado | 503 | La síntesis de voz está desactivada |
| Texto vacío | 400 | No hay texto que sintetizar |
| Texto por encima de `tts_max_chars` | 413 | El texto es demasiado largo |
| Fallo de edge-tts | 502 | No he podido generar la voz |

**`app/config.py`**: `tts_enabled: bool = True`, `tts_voice: str = "es-ES-ElviraNeural"`, `tts_max_chars: int = 600`.

**`requirements.txt`**: `edge-tts>=7.0`.

### Frontend

Todo el cambio vive en `frontend/src/lib/voice.ts`. `FacePanel.tsx` y `FacePage.tsx` **no se tocan**: `speakSpanish(text, onEnd)` conserva su firma y su contrato de cancelación.

**`splitIntoSpeechChunks(text: string): string[]`** — función pura, sin DOM. Aplica `cleanSpeechText`, corta por final de frase (`.`, `?`, `!`, `…`, salto de línea), fusiona los fragmentos de menos de `MIN_CHUNK_CHARS` con el siguiente para que no queden trozos sueltos tipo "Sí.", y parte por coma o espacio lo que exceda `MAX_CHUNK_CHARS`. Se prueba con una tabla de entradas y salidas.

**`speakWithBrowser(text, onEnd)`** — la implementación actual de `speakSpanish`, renombrada. Sigue siendo el camino de fallback.

**`speakSpanish(text, onEnd)`** — pasa a coordinar una cola. Pide el fragmento *i* a `/api/tts` con `apiBlob` y, mientras suena en un `HTMLAudioElement`, ya está pidiendo el *i+1*. Devuelve la misma función de cancelación de antes.

`MAX_CHUNK_CHARS` en el frontend debe coincidir con `tts_max_chars` en el backend. La validación del servidor es la red de seguridad, no la fuente de la verdad.

## Flujo de datos

1. `FacePanel` recibe la respuesta de `/api/voz` y llama a `speakSpanish(respuesta, onEnd)`.
2. `splitIntoSpeechChunks` limpia y trocea el texto. Si no queda nada legible, se invoca `onEnd` y se termina.
3. Se lanza la petición del fragmento 0.
4. Por cada fragmento: se espera su audio, se lanza la petición del siguiente, y se reproduce el actual. La latencia de red del fragmento *i+1* queda escondida bajo la reproducción del *i*.
5. Al terminar el último fragmento se invoca `onEnd`, que devuelve la cara a `idle`.

## Errores y cancelación

- **Fallo de red o del servidor en el fragmento *i***: se abandona la cola y se locutan los fragmentos restantes (`chunks.slice(i)`) con `speakWithBrowser`. Si el fallo es en el fragmento 0, equivale a que toda la respuesta salga por el navegador. Morgana nunca se queda callada.
- **Fallo de reproducción** (`play()` rechazado, formato no soportado): mismo tratamiento que el fallo de red.
- **Cancelación** (el usuario toca la cara mientras Morgana habla): se aborta el `fetch` en curso con `AbortController`, se pausa el audio, se revocan las URLs de objeto y se cancela la síntesis del navegador si estaba activa. Igual que hoy, cancelar **no** invoca `onEnd`.
- Cada petición lleva un `.catch()` de cortesía en el momento de crearse, para que abortar la petición adelantada no produzca un rechazo sin gestionar.
- Toda `URL.createObjectURL` se revoca al terminar o fallar su reproducción.

## Pruebas

**Backend** (`unittest` + `TestClient`, como `tests/test_api.py`):

- `/api/tts` devuelve `audio/mpeg` con el cuerpo que produce el ejecutor, sustituyendo `edge_speech.sintetizar`.
- Rechaza sin autenticación.
- Rechaza texto vacío (400) y texto por encima del límite (413).
- Devuelve 502 cuando el ejecutor lanza una excepción.
- Devuelve 503 con `tts_enabled` en falso.
- `sintetizar` acumula los eventos de audio y descarta los demás; lanza error si no llega audio.

**Frontend** (`vitest` + `jsdom`):

- `splitIntoSpeechChunks`: frases sueltas, fusión de fragmentos cortos, partido de frases largas, texto vacío tras limpiar, markdown y URLs eliminados por `cleanSpeechText`.
- `speakSpanish`: pide los fragmentos en orden, adelanta la petición del siguiente mientras reproduce, invoca `onEnd` una sola vez al final.
- `speakSpanish`: cae a `speechSynthesis` cuando `/api/tts` falla, y con los fragmentos que faltaban.
- `speakSpanish`: al cancelar, no invoca `onEnd`, aborta la petición en vuelo y para el audio.

`jsdom` no implementa `HTMLMediaElement.play()`, así que las pruebas de la cola sustituyen `play`, `pause` y el disparo de `ended` sobre el prototipo.

## Fuera de alcance

- Selector de voz en la pantalla de Ajustes.
- Caché de audio en servidor.
- Sincronizar el tono de voz con el estado emocional de la cara. Requiere un motor que acepte instrucciones de estilo, y todos los que lo hacen hoy son de pago.

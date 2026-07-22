# Morgana Cara Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Convert the protected \`/cara\` placeholder into a tap-driven Spanish voice conversation interface using the supplied animated cat face.

**Architecture:** The browser records short audio clips and detects silence locally. A new authenticated multipart endpoint transcribes each clip with Groq Whisper, passes the text through the existing message core, and returns a normalized spoken response. The device uses its Spanish speech synthesis voice while the React page drives the face through idle, listening, thinking, and speaking states.

**Tech Stack:** FastAPI, AsyncGroq, React 19, TypeScript, MediaRecorder, Web Audio API, Web Speech API, unittest, Vitest, Testing Library.

## Global Constraints

- Serve the installed PWA through the existing HTTPS origin.
- Use \`whisper-large-v3-turbo\` with language \`es\`.
- Keep audio only in memory; never persist recordings.
- Stop after 800 ms of silence following detected speech and after an absolute 30-second maximum.
- Accept at most 5 MB per recording.
- Prefer a known feminine Spanish device voice and fall back to the first Spanish voice.
- Preserve \`prefers-reduced-motion\`, keyboard focus, and screen-reader labels.
- Do not add MediaPipe, local Whisper, external TTS, streaming, wake-word support, or a visible chat history.

---

### Task 1: Groq transcription boundary

**Files:**
- Create: \`app/executors/groq_speech.py\`
- Create: \`tests/test_groq_speech.py\`
- Modify: \`app/config.py\`
- Modify: \`.env.example\`

**Interfaces:**
- Consumes: \`settings.groq_api_key\`.
- Produces: \`async transcribir(nombre: str, audio: bytes) -> str\`, \`settings.groq_speech_model\`, and \`settings.voice_max_audio_bytes\`.

- [ ] **Step 1: Write the failing transcription tests**

~~~python
class GroqSpeechTests(IsolatedAsyncioTestCase):
    async def test_transcribe_spanish_audio_with_configured_model(self):
        fake = FakeGroqSpeechClient(" hola ")
        with patch.object(groq_speech, "_client", fake), patch.object(
            settings, "groq_speech_model", "whisper-test"
        ):
            text = await groq_speech.transcribir("voz.webm", b"audio")
        self.assertEqual(text, "hola")
        self.assertEqual(
            fake.calls[0],
            {
                "file": ("voz.webm", b"audio"),
                "model": "whisper-test",
                "language": "es",
                "response_format": "json",
                "temperature": 0.0,
            },
        )

    async def test_empty_provider_text_returns_empty_string(self):
        with patch.object(groq_speech, "_client", FakeGroqSpeechClient(None)):
            self.assertEqual(await groq_speech.transcribir("voz.webm", b"x"), "")
~~~

- [ ] **Step 2: Run the test and verify RED**

Run: \`python -m unittest tests.test_groq_speech -v\`
Expected: FAIL because \`app.executors.groq_speech\` does not exist.

- [ ] **Step 3: Implement the AsyncGroq adapter and settings**

~~~python
# app/executors/groq_speech.py
from groq import AsyncGroq
from ..config import settings

_client: AsyncGroq | None = None

def client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client

async def transcribir(nombre: str, audio: bytes) -> str:
    result = await client().audio.transcriptions.create(
        file=(nombre, audio),
        model=settings.groq_speech_model,
        language="es",
        response_format="json",
        temperature=0.0,
    )
    return (result.text or "").strip()
~~~

Add \`groq_speech_model: str = "whisper-large-v3-turbo"\` and \`voice_max_audio_bytes: int = 5_000_000\` to \`Settings\`, with matching optional entries in \`.env.example\`.

- [ ] **Step 4: Run the test and verify GREEN**

Run: \`python -m unittest tests.test_groq_speech -v\`
Expected: both tests PASS.

- [ ] **Step 5: Commit the transcription boundary**

~~~powershell
git add app/executors/groq_speech.py app/config.py .env.example tests/test_groq_speech.py
git commit -m "feat: add Groq voice transcription"
~~~

### Task 2: Authenticated voice endpoint

**Files:**
- Modify: \`requirements.txt\`
- Modify: \`app/api.py\`
- Modify: \`tests/test_api.py\`

**Interfaces:**
- Consumes: \`groq_speech.transcribir(nombre, audio)\`, \`message_core.procesar_mensaje(user, texto, canal="pwa_voz")\`, and \`settings.voice_max_audio_bytes\`.
- Produces: \`POST /api/voz\` with multipart field \`audio\` and response type \`VoiceResponse\`.

- [ ] **Step 1: Write failing API tests for quick and agentic responses**

~~~python
def test_voz_transcribe_y_reutiliza_core(self):
    result = ResultadoMensaje("rapida", respuesta="Respuesta")
    with patch(
        "app.api.groq_speech.transcribir", AsyncMock(return_value="Pregunta")
    ), patch(
        "app.api.message_core.procesar_mensaje", AsyncMock(return_value=result)
    ) as process:
        response = self.client.post(
            "/api/voz",
            files={"audio": ("voz.webm", b"audio", "audio/webm")},
            headers=self.headers,
        )
    self.assertEqual(response.status_code, 200)
    self.assertEqual(
        response.json(),
        {"via": "rapida", "transcripcion": "Pregunta", "respuesta": "Respuesta"},
    )
    process.assert_awaited_once_with(self.user, "Pregunta", canal="pwa_voz")

def test_voz_agentica_devuelve_confirmacion_hablable(self):
    result = ResultadoMensaje("agentica", task={"id": "t1"})
    with patch(
        "app.api.groq_speech.transcribir", AsyncMock(return_value="Haz el cambio")
    ), patch(
        "app.api.message_core.procesar_mensaje", AsyncMock(return_value=result)
    ):
        response = self.client.post(
            "/api/voz",
            files={"audio": ("voz.webm", b"audio", "audio/webm")},
            headers=self.headers,
        )
    self.assertEqual(response.json()["task_id"], "t1")
    self.assertIn("tarea", response.json()["respuesta"].lower())
~~~

- [ ] **Step 2: Run focused tests and verify RED**

Run: \`python -m unittest tests.test_api.ApiTests.test_voz_transcribe_y_reutiliza_core tests.test_api.ApiTests.test_voz_agentica_devuelve_confirmacion_hablable -v\`
Expected: FAIL with 404 for \`/api/voz\`.

- [ ] **Step 3: Add validation tests**

Cover unauthenticated requests, unsupported \`text/plain\`, empty uploads, uploads above \`voice_max_audio_bytes\`, and an empty Whisper transcript. Expected status codes are 401, 415, 400, 413, and 422 respectively, each using the existing \`{"error": "..."}\` envelope.

- [ ] **Step 4: Implement the multipart endpoint**

Add \`python-multipart>=0.0.9\` to requirements and define:

~~~python
SUPPORTED_VOICE_TYPES = {
    "audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg",
    "audio/wav", "audio/x-wav", "audio/flac",
}

@api_router.post("/voz")
async def voz(
    audio: UploadFile = File(...),
    user: dict = Depends(auth.current_user),
):
    if audio.content_type not in SUPPORTED_VOICE_TYPES:
        raise HTTPException(status_code=415, detail="Formato de audio no compatible")
    content = await audio.read(settings.voice_max_audio_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="El audio está vacío")
    if len(content) > settings.voice_max_audio_bytes:
        raise HTTPException(status_code=413, detail="El audio es demasiado grande")
    transcript = await groq_speech.transcribir(audio.filename or "voz.webm", content)
    if not transcript:
        raise HTTPException(status_code=422, detail="No he detectado voz")
    result = await message_core.procesar_mensaje(user, transcript, canal="pwa_voz")
    if result.via == "rapida":
        return {"via": "rapida", "transcripcion": transcript, "respuesta": result.respuesta}
    if result.task:
        return {
            "via": "agentica",
            "transcripcion": transcript,
            "task_id": result.task["id"],
            "respuesta": "He creado la tarea y seguiré trabajando en segundo plano.",
        }
    raise the same controlled project-resolution errors used by \`/api/mensaje\`.
~~~

Extract the shared message-result error mapping only if needed to avoid duplicating the existing project-resolution branches.

- [ ] **Step 5: Run backend tests and verify GREEN**

Run: \`python -m unittest tests.test_api tests.test_groq_speech -v\`
Expected: all tests PASS.

- [ ] **Step 6: Commit the voice API**

~~~powershell
git add requirements.txt app/api.py tests/test_api.py
git commit -m "feat: add authenticated voice endpoint"
~~~

### Task 3: Browser audio and speech adapters

**Files:**
- Create: \`frontend/src/lib/voice.ts\`
- Create: \`frontend/src/lib/voice.test.ts\`
- Modify: \`frontend/src/lib/api.ts\`
- Modify: \`frontend/src/lib/api.test.ts\`
- Modify: \`frontend/src/types.ts\`

**Interfaces:**
- Produces: \`VoiceCapture\`, \`startVoiceCapture(onSilence)\`, \`speakSpanish(text, onEnd)\`, \`cleanSpeechText(text)\`, \`selectSpanishVoice(voices)\`, and \`VoiceResponse\`.

- [ ] **Step 1: Write a failing multipart API test**

~~~typescript
it("does not force JSON content type for FormData", async () => {
  const fetchMock = vi.fn(async (_url, init) => Response.json({ ok: true }));
  vi.stubGlobal("fetch", fetchMock);
  await apiFetch("/api/voz", { method: "POST", body: new FormData() });
  const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
  expect(headers.has("Content-Type")).toBe(false);
});
~~~

- [ ] **Step 2: Run the API test and verify RED**

Run: \`npm test -- --run src/lib/api.test.ts\` from \`frontend\`.
Expected: FAIL because \`apiFetch\` sets \`application/json\`.

- [ ] **Step 3: Make FormData handling GREEN**

Only set JSON content type when \`init.body\` is present and is not a \`FormData\` instance.

- [ ] **Step 4: Write failing voice utility tests**

~~~typescript
it("prefers a known feminine Spanish voice", () => {
  const voices = [
    makeVoice("Carlos", "es-ES"),
    makeVoice("Mónica", "es-ES"),
  ];
  expect(selectSpanishVoice(voices)?.name).toBe("Mónica");
});

it("turns markdown into speakable text", () => {
  expect(cleanSpeechText("**Hola** [mundo](https://example.com)")).toBe("Hola mundo");
});
~~~

Add a MediaRecorder fake and fake analyser to prove that \`startVoiceCapture\` resolves a Blob on manual stop, calls \`onSilence\` once after 800 ms of post-speech silence, stops all stream tracks, and enforces the 30-second maximum.

- [ ] **Step 5: Run voice tests and verify RED**

Run: \`npm test -- --run src/lib/voice.test.ts\` from \`frontend\`.
Expected: FAIL because \`voice.ts\` does not exist.

- [ ] **Step 6: Implement the adapters**

~~~typescript
export interface VoiceCapture {
  stop(): Promise<Blob>;
  cancel(): void;
}

export async function startVoiceCapture(
  onSilence: () => void,
): Promise<VoiceCapture> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  // Pick a supported WebM, Ogg, or MP4 MediaRecorder MIME type.
  // Feed the stream into an AnalyserNode, mark speech above the RMS threshold,
  // and call onSilence once after 800 ms below threshold.
  // stop() resolves the collected Blob; cancel() releases without submitting.
}
~~~

\`speakSpanish\` must set \`utterance.lang = "es-ES"\`, choose \`selectSpanishVoice(speechSynthesis.getVoices())\`, register \`onend\` and \`onerror\`, and return a cancel function. \`cleanSpeechText\` removes Markdown formatting and raw URLs without removing ordinary punctuation.

- [ ] **Step 7: Run frontend library tests and verify GREEN**

Run: \`npm test -- --run src/lib/api.test.ts src/lib/voice.test.ts\` from \`frontend\`.
Expected: all tests PASS.

- [ ] **Step 8: Commit browser voice adapters**

~~~powershell
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/src/lib/voice.ts frontend/src/lib/voice.test.ts frontend/src/types.ts
git commit -m "feat: add browser voice adapters"
~~~

### Task 4: Face conversation state machine

**Files:**
- Modify: \`frontend/src/pages/FacePage.tsx\`
- Create: \`frontend/src/pages/FacePage.test.tsx\`

**Interfaces:**
- Consumes: \`startVoiceCapture\`, \`speakSpanish\`, \`apiFetch<VoiceResponse>\`, and the \`VoiceResponse\` union.
- Produces: the user-visible \`idle | listening | thinking | speaking\` interaction.

- [ ] **Step 1: Write the failing manual-tap state test**

Mock \`../lib/voice\`. The first click on the button named \`Hablar con Morgana\` must show \`Escuchando\`; the second must call capture.stop and show \`Pensando\`; resolving the API with a quick response must call \`speakSpanish("Respuesta", onEnd)\` and show \`Hablando\`; invoking \`onEnd\` must restore \`Toca a Morgana para hablar\`.

- [ ] **Step 2: Run the page test and verify RED**

Run: \`npm test -- --run src/pages/FacePage.test.tsx\` from \`frontend\`.
Expected: FAIL because the current placeholder has no voice control.

- [ ] **Step 3: Add failing interruption, error, and cleanup tests**

Verify that the silence callback follows the same stop-and-send path, tapping while speaking cancels current speech before starting a new capture, duplicate taps while thinking do nothing, permission/API errors render an alert and return to idle, and unmount cancels capture and speech.

- [ ] **Step 4: Implement the page state machine and SVG**

Use refs for the active capture, speech cancel callback, mounted flag, and in-flight guard. Render the supplied cat SVG inside one \`button type="button"\` whose visual root receives the current state class. Use these status strings:

- idle: \`Toca a Morgana para hablar\`
- listening: \`Te escucho · toca para enviar\`
- thinking: \`Estoy pensando\`
- speaking: \`Te respondo · toca para interrumpir\`

On an agentic response, speak its \`respuesta\` confirmation exactly like a quick response.

- [ ] **Step 5: Run the page tests and verify GREEN**

Run: \`npm test -- --run src/pages/FacePage.test.tsx\` from \`frontend\`.
Expected: all tests PASS.

- [ ] **Step 6: Commit the interaction**

~~~powershell
git add frontend/src/pages/FacePage.tsx frontend/src/pages/FacePage.test.tsx
git commit -m "feat: make Morgana face conversational"
~~~

### Task 5: Responsive face styling and full verification

**Files:**
- Modify: \`frontend/src/styles.css\`
- Modify: \`README.md\`
- Modify: \`IMPLEMENTACION.md\`

**Interfaces:**
- Consumes: the state class names and SVG class names emitted by \`FacePage\`.
- Produces: responsive visuals matching \`morgana-cara.html\`.

- [ ] **Step 1: Port the visual system**

Add scoped \`.face-*\` styles for the nocturnal radial stage, halo, pulse ring, floating cat, ear flick, blinking and happy eyes, blush, whiskers, mouth, thinking dots, and the four state variants. Reset the face button without removing \`:focus-visible\`. Size the hit target to the entire cat stage in portrait and landscape and account for \`env(safe-area-inset-bottom)\`.

- [ ] **Step 2: Preserve accessibility and reduced motion**

Under \`prefers-reduced-motion: reduce\`, disable ambient and state animations while retaining the visible state changes. Ensure status and error text meet contrast requirements and remain outside the SVG's pointer target.

- [ ] **Step 3: Update operator documentation**

Document HTTPS and microphone permission requirements, the \`GROQ_SPEECH_MODEL\` and \`VOICE_MAX_AUDIO_BYTES\` settings, browser-provided Spanish TTS behavior, and the fact that recordings are not persisted.

- [ ] **Step 4: Run all verification**

Run:

~~~powershell
python -m unittest discover -s tests -v
Set-Location frontend
npm test -- --run
npm run build
Set-Location ..
~~~

Expected: every Python and Vitest test passes, TypeScript emits no errors, and Vite produces \`frontend/dist\`.

- [ ] **Step 5: Inspect the rendered route**

Run the app locally, open \`/cara\` at mobile and tablet viewport sizes, and verify the whole cat is tappable, the bottom navigation does not overlap status copy, reduced motion works, and no horizontal scrolling appears.

- [ ] **Step 6: Commit the finished experience**

~~~powershell
git add frontend/src/styles.css README.md IMPLEMENTACION.md
git commit -m "feat: finish responsive voice face"
~~~

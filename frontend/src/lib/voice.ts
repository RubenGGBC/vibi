const SILENCE_MS = 800;
const MAX_RECORDING_MS = 30_000;
const SPEECH_THRESHOLD = 0.028;

const recorderTypes = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

const feminineVoiceNames = [
  "monica",
  "monica compact",
  "paulina",
  "luciana",
  "helena",
  "elvira",
  "sabina",
  "marisol",
  "sofia",
  "isabela",
  "carmen",
  "conchita",
  "google espanol",
];

type WebkitWindow = Window & typeof globalThis & {
  webkitAudioContext?: typeof AudioContext;
};

export interface VoiceCapture {
  stop(): Promise<Blob>;
  cancel(): void;
}

const normalize = (value: string): string =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase();

export function supportsVoiceConversation(): boolean {
  const AudioContextClass =
    window.AudioContext ?? (window as WebkitWindow).webkitAudioContext;
  return Boolean(
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
      typeof MediaRecorder !== "undefined" &&
      AudioContextClass &&
      window.speechSynthesis &&
      typeof SpeechSynthesisUtterance !== "undefined",
  );
}

export async function startVoiceCapture(
  onSilence: () => void,
): Promise<VoiceCapture> {
  if (!supportsVoiceConversation()) {
    throw new DOMException(
      "Este navegador no admite conversación por voz",
      "NotSupportedError",
    );
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
    },
  });
  const mimeType = recorderTypes.find((type) =>
    MediaRecorder.isTypeSupported(type),
  );
  const recorder = new MediaRecorder(
    stream,
    mimeType ? { mimeType } : undefined,
  );
  const AudioContextClass =
    window.AudioContext ?? (window as WebkitWindow).webkitAudioContext;

  if (!AudioContextClass) {
    stream.getTracks().forEach((track) => track.stop());
    throw new DOMException(
      "Este navegador no permite analizar el micrófono",
      "NotSupportedError",
    );
  }

  const audioContext = new AudioContextClass();
  await audioContext.resume();
  const source = audioContext.createMediaStreamSource(stream);
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0.18;
  source.connect(analyser);

  const samples = new Uint8Array(analyser.fftSize);
  const chunks: BlobPart[] = [];
  let animationFrame = 0;
  let maximumTimer = 0;
  let voiceDetected = false;
  let silentSince: number | null = null;
  let silenceTriggered = false;
  let stopping = false;
  let released = false;

  let resolveRecording!: (blob: Blob) => void;
  let rejectRecording!: (error: Error) => void;
  const recording = new Promise<Blob>((resolve, reject) => {
    resolveRecording = resolve;
    rejectRecording = reject;
  });

  const release = () => {
    if (released) return;
    released = true;
    window.cancelAnimationFrame(animationFrame);
    window.clearTimeout(maximumTimer);
    source.disconnect();
    analyser.disconnect();
    stream.getTracks().forEach((track) => track.stop());
    void audioContext.close().catch(() => undefined);
  };

  const triggerSilence = () => {
    if (silenceTriggered || stopping) return;
    silenceTriggered = true;
    window.queueMicrotask(onSilence);
  };

  const monitor = () => {
    analyser.getByteTimeDomainData(samples);
    let energy = 0;
    for (const sample of samples) {
      const amplitude = (sample - 128) / 128;
      energy += amplitude * amplitude;
    }
    const rms = Math.sqrt(energy / samples.length);
    const now = performance.now();

    if (rms >= SPEECH_THRESHOLD) {
      voiceDetected = true;
      silentSince = null;
    } else if (voiceDetected) {
      silentSince ??= now;
      if (now - silentSince >= SILENCE_MS) {
        triggerSilence();
        return;
      }
    }
    animationFrame = window.requestAnimationFrame(monitor);
  };

  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size) chunks.push(event.data);
  });
  recorder.addEventListener("stop", () => {
    release();
    resolveRecording(
      new Blob(chunks, { type: recorder.mimeType || mimeType || "audio/webm" }),
    );
  });
  recorder.addEventListener("error", () => {
    release();
    rejectRecording(new Error("No se pudo grabar el audio"));
  });

  recorder.start(250);
  animationFrame = window.requestAnimationFrame(monitor);
  maximumTimer = window.setTimeout(triggerSilence, MAX_RECORDING_MS);

  const stop = (): Promise<Blob> => {
    if (!stopping) {
      stopping = true;
      if (recorder.state === "inactive") {
        release();
        resolveRecording(
          new Blob(chunks, {
            type: recorder.mimeType || mimeType || "audio/webm",
          }),
        );
      } else {
        recorder.stop();
      }
    }
    return recording;
  };

  return {
    stop,
    cancel: () => {
      void stop();
    },
  };
}

export function selectSpanishVoice(
  voices: SpeechSynthesisVoice[],
): SpeechSynthesisVoice | undefined {
  const spanish = voices.filter((voice) =>
    voice.lang.toLocaleLowerCase().startsWith("es"),
  );
  return (
    spanish.find((voice) => {
      const name = normalize(voice.name);
      return feminineVoiceNames.some((candidate) => name.includes(candidate));
    }) ?? spanish[0]
  );
}

export function cleanSpeechText(text: string): string {
  return text
    .replace(/```(?:\w+)?\s*([\s\S]*?)```/g, "$1")
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/^\s{0,3}(?:#{1,6}|>|[-*+] |\d+\. )\s*/gm, "")
    .replace(/[*_~`]/g, "")
    .replace(/\[(?:\d+|[a-z]+)]/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function speakSpanish(text: string, onEnd: () => void): () => void {
  const speakable = cleanSpeechText(text);
  if (!speakable) {
    window.queueMicrotask(onEnd);
    return () => undefined;
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(speakable);
  utterance.lang = "es-ES";
  utterance.rate = 1.02;
  utterance.pitch = 1.04;
  const voice = selectSpanishVoice(window.speechSynthesis.getVoices());
  if (voice) utterance.voice = voice;

  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    onEnd();
  };
  utterance.onend = finish;
  utterance.onerror = finish;
  window.speechSynthesis.speak(utterance);

  return () => {
    if (finished) return;
    finished = true;
    utterance.onend = null;
    utterance.onerror = null;
    window.speechSynthesis.cancel();
  };
}

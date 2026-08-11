import { apiBlob } from "./api";

const SILENCE_MS = 800;
const MAX_RECORDING_MS = 30_000;
const SPEECH_THRESHOLD = 0.028;

// Debe coincidir con TTS_MAX_CHARS en el backend.
const MAX_CHUNK_CHARS = 600;
// Por debajo de esto un fragmento suena cortado: se fusiona con el siguiente.
const MIN_CHUNK_CHARS = 40;

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

const splitLongSentence = (sentence: string): string[] => {
  const parts: string[] = [];
  let rest = sentence;
  while (rest.length > MAX_CHUNK_CHARS) {
    const head = rest.slice(0, MAX_CHUNK_CHARS);
    const boundary = Math.max(
      head.lastIndexOf(", "),
      head.lastIndexOf("; "),
      head.lastIndexOf(" "),
    );
    // Solo cortamos por puntuación si cae en la segunda mitad; si no, el
    // fragmento resultante sería ridículamente corto.
    const cut = boundary > MAX_CHUNK_CHARS / 2 ? boundary + 1 : MAX_CHUNK_CHARS;
    parts.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) parts.push(rest);
  return parts;
};

/**
 * Extrae del buffer las frases ya cerradas y devuelve lo que queda a medias.
 *
 * Es la pieza que permite locutar mientras el modelo aún escribe: se llama con
 * el texto acumulado y solo suelta lo que ya se puede decir sin que suene
 * cortado. Con `flush` se vacía el resto, aunque no cierre con puntuación.
 */
export function takeSpeakableSentences(
  buffer: string,
  options: { flush?: boolean } = {},
): { chunks: string[]; rest: string } {
  const flush = options.flush ?? false;
  // Una frase está cerrada cuando tras su signo final viene algo más: si no,
  // puede que el modelo esté a mitad de "3.14" o de unos puntos suspensivos.
  const closed = /^[\s\S]*[.!?…](?=\s)/.exec(buffer);
  const cerradas = flush ? buffer : (closed?.[0] ?? "");
  const pendiente = flush ? "" : buffer.slice(cerradas.length);

  const speakable = cleanSpeechText(cerradas);
  if (!speakable) return { chunks: [], rest: flush ? "" : buffer };
  // Sin flush no vale la pena locutar una migaja: espera al siguiente delta.
  if (!flush && speakable.length < MIN_CHUNK_CHARS) {
    return { chunks: [], rest: buffer };
  }

  return { chunks: splitIntoSpeechChunks(speakable), rest: pendiente.trimStart() };
}

/** Trocea una respuesta en fragmentos locutables, por frases. */
export function splitIntoSpeechChunks(text: string): string[] {
  const speakable = cleanSpeechText(text);
  if (!speakable) return [];

  const sentences = speakable.match(/[^.!?…]+[.!?…]*/g) ?? [speakable];
  const chunks: string[] = [];
  let buffer = "";

  for (const raw of sentences) {
    const sentence = raw.trim();
    if (!sentence) continue;

    const candidate = buffer ? `${buffer} ${sentence}` : sentence;
    if (candidate.length <= MAX_CHUNK_CHARS) {
      buffer = candidate;
      if (buffer.length >= MIN_CHUNK_CHARS) {
        chunks.push(buffer);
        buffer = "";
      }
      continue;
    }

    if (buffer) {
      chunks.push(buffer);
      buffer = "";
    }
    chunks.push(...splitLongSentence(sentence));
  }

  if (buffer) chunks.push(buffer);
  return chunks;
}

/** Locuta con la voz del sistema. Es el fallback cuando /api/tts falla. */
export function speakWithBrowser(text: string, onEnd: () => void): () => void {
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

/**
 * Lo que dice Morgana nada más soltar el micrófono, mientras piensa.
 *
 * Medido: locutadas duran entre 1,4 s ("Voy.") y 2,1 s ("Miro y te cuento."),
 * bastante más de lo que sugiere su longitud porque edge-tts añade silencio de
 * relleno. Como un turno tarda ~1,2 s como mínimo, eso significa que en las
 * preguntas más rápidas la respuesta real sale medio segundo más tarde: el
 * cambio es a favor de no dejar silencio, no de acabar antes. Mantenerlas
 * cortas es justamente lo que acota ese peaje.
 */
export const ACKNOWLEDGEMENTS = [
  "Vale.",
  "Voy.",
  "Déjame ver.",
  "Un momento.",
  "Ahora te digo.",
  "Miro y te cuento.",
] as const;

const acknowledgementAudio: Blob[] = [];
let prewarming: Promise<void> | null = null;

/** Cómo se pide una muletilla cuando no se dice otra cosa: la API de la PWA. */
const pedirPorLaApi = (texto: string): Promise<Blob> =>
  apiBlob("/api/tts", { method: "POST", body: JSON.stringify({ texto }) });

/**
 * Sintetiza las muletillas y las deja en memoria.
 *
 * Sin esto habría que pedirlas al vuelo y tardarían lo mismo que cualquier
 * fragmento (~0,4 s), justo el hueco que vienen a disimular.
 *
 * `sintetizar` existe porque el companion de escritorio no habla por `apiBlob`:
 * pide el audio a su propio endpoint, con su host y su token. Sin poder pasar
 * su vía se quedaba sin muletillas y en silencio hasta que el modelo avisaba
 * por su cuenta, que medido tarda casi cinco segundos.
 */
export function prewarmAcknowledgements(
  sintetizar: (texto: string) => Promise<Blob | null> = pedirPorLaApi,
): Promise<void> {
  if (acknowledgementAudio.length) return Promise.resolve();
  prewarming ??= Promise.all(
    ACKNOWLEDGEMENTS.map(async (texto) => {
      try {
        return await sintetizar(texto);
      } catch {
        // Sin voz neuronal no hay muletilla, pero la conversación sigue.
        return null;
      }
    }),
  ).then((blobs) => {
    acknowledgementAudio.push(...blobs.filter((blob): blob is Blob => !!blob));
    prewarming = null;
  });
  return prewarming;
}

/** Una muletilla ya sintetizada, o null si aún no hay ninguna lista. */
export function takeAcknowledgement(): Blob | null {
  if (!acknowledgementAudio.length) return null;
  const index = Math.floor(Math.random() * acknowledgementAudio.length);
  return acknowledgementAudio[index] ?? null;
}

export interface SpeechStream {
  /**
   * Texto acumulado del turno hasta ahora; se locuta lo que ya esté cerrado.
   *
   * `boundary` marca que el bloque de texto ha terminado aunque el turno siga:
   * es lo que pasa cuando Morgana avisa de que va a buscar algo y llama a la
   * herramienta acto seguido. Sin él, esa frase se quedaría esperando un
   * espacio detrás del punto que no llega hasta después de la herramienta.
   */
  push(fullText: string, options?: { boundary?: boolean }): void;
  /** No llegará más texto: vacía lo que quede y termina al acabar la cola. */
  end(): void;
  cancel(): void;
}

export type SpeechAudioRequest = (
  text: string,
  signal: AbortSignal,
) => Promise<Blob>;

/**
 * Cola de locución que acepta texto mientras el modelo aún lo está escribiendo.
 *
 * Cada frase cerrada se manda a sintetizar en cuanto aparece, así la síntesis
 * de las siguientes ocurre mientras suena la actual y la primera sílaba no
 * espera a que termine la respuesta entera. Si el TTS neuronal falla, lo que
 * quede por decir sale por la voz del navegador: Morgana no se queda muda.
 */
export function createSpeechStream(
  onEnd: () => void,
  options: {
    acknowledgement?: Blob | null;
    requestAudio?: SpeechAudioRequest;
  } = {},
): SpeechStream {
  const controller = new AbortController();
  // `optional` marca el audio que puede perderse sin consecuencias: si falla
  // una muletilla no tiene sentido arrastrar la respuesta al fallback.
  const queue: { text: string; audio: Promise<Blob>; optional?: boolean }[] = [];
  let buffer = "";
  let seen = "";
  let ended = false;
  let draining = false;
  let cancelled = false;
  let finished = false;
  let playing: HTMLAudioElement | null = null;
  let browserCancel: (() => void) | null = null;

  const finish = () => {
    if (finished) return;
    finished = true;
    onEnd();
  };

  const request = (chunk: string): Promise<Blob> => {
    const pending = options.requestAudio
      ? options.requestAudio(chunk, controller.signal)
      : apiBlob("/api/tts", {
          method: "POST",
          body: JSON.stringify({ texto: chunk }),
          signal: controller.signal,
        });
    // Si abandonamos la cola, la petición adelantada no debe quedar
    // como un rechazo sin gestionar.
    pending.catch(() => undefined);
    return pending;
  };

  const play = (blob: Blob): Promise<void> =>
    new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const element = new Audio(url);
      playing = element;
      const release = () => {
        URL.revokeObjectURL(url);
        if (playing === element) playing = null;
      };
      element.addEventListener("ended", () => {
        release();
        resolve();
      });
      element.addEventListener("error", () => {
        release();
        reject(new Error("No se pudo reproducir el audio"));
      });
      void element.play().catch((error: unknown) => {
        release();
        reject(error instanceof Error ? error : new Error("Reproducción bloqueada"));
      });
    });

  const fallback = (remaining: string[]) => {
    if (cancelled) return;
    browserCancel = speakWithBrowser(remaining.join(" "), () => {
      browserCancel = null;
      finish();
    });
  };

  const drain = async () => {
    if (draining) return;
    draining = true;
    while (queue.length) {
      const item = queue.shift();
      if (!item) break;
      try {
        const blob = await item.audio;
        if (cancelled) return;
        await play(blob);
      } catch {
        if (cancelled) return;
        // Una muletilla que falla se descarta y ya: lo que importa es la
        // respuesta, que sigue su curso normal.
        if (item.optional) continue;
        // Arrastra al fallback lo que ya estaba en cola, o se perdería.
        const pendientes = [item.text, ...queue.map(({ text }) => text)];
        queue.length = 0;
        draining = false;
        fallback(pendientes);
        return;
      }
      if (cancelled) return;
    }
    draining = false;
    if (ended) finish();
  };

  const drenar = (flush: boolean) => {
    const { chunks, rest } = takeSpeakableSentences(buffer, { flush });
    buffer = rest;
    for (const chunk of chunks) queue.push({ text: chunk, audio: request(chunk) });
    if (queue.length) void drain();
  };

  // Va primera en la cola, así que suena ya y la respuesta espera su turno:
  // el orden lo garantiza la propia cola, sin temporizadores ni solapes.
  if (options.acknowledgement) {
    queue.push({
      text: "",
      audio: Promise.resolve(options.acknowledgement),
      optional: true,
    });
    void drain();
  }

  return {
    push(fullText: string, options: { boundary?: boolean } = {}) {
      if (cancelled || ended) return;
      // Llega el acumulado del turno, así que hay que quedarse solo con la
      // parte nueva. Se compara por prefijo y no por longitud: el texto final
      // del turno viene recortado y sería más corto que lo ya locutado.
      if (fullText.startsWith(seen)) {
        buffer += fullText.slice(seen.length);
        seen = fullText;
      } else if (seen.startsWith(fullText)) {
        // Nada que no se haya dicho ya (el cierre recortado del turno).
        return;
      } else if (fullText && seen.trimEnd().endsWith(fullText.trimEnd())) {
        // El cierre del turno trae solo el bloque posterior a la herramienta:
        // el acuse que iba delante no está en la respuesta guardada, así que
        // no es prefijo de lo ya visto pero tampoco es texto nuevo.
        return;
      } else {
        // Diverge de verdad: el turno se reinició y toca empezar de cero.
        buffer = fullText;
        seen = fullText;
      }
      drenar(options.boundary ?? false);
    },
    end() {
      if (cancelled || ended) return;
      ended = true;
      drenar(true);
      // Sin nada en cola ni sonando, no habrá un drain que cierre por nosotros.
      // Vía microtask para que onEnd nunca llegue antes de que quien nos creó
      // haya podido guardarse el cancelador.
      if (!queue.length && !draining) window.queueMicrotask(finish);
    },
    cancel() {
      if (finished) return;
      finished = true;
      cancelled = true;
      queue.length = 0;
      controller.abort();
      if (playing) {
        playing.pause();
        playing = null;
      }
      browserCancel?.();
      browserCancel = null;
    },
  };
}

/** Locuta una respuesta ya completa. Atajo sobre `createSpeechStream`. */
export function speakSpanish(text: string, onEnd: () => void): () => void {
  const stream = createSpeechStream(onEnd);
  stream.push(text);
  stream.end();
  return () => stream.cancel();
}

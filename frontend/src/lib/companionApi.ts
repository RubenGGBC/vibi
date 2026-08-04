import type { VoiceResponse } from "../types";

const SETTINGS_KEY = "morgana.companion.settings";

export interface CompanionSettings {
  apiBase: string;
  nodeToken: string;
  nodeName: string;
}

interface RegisterNodeResponse {
  token: string;
  nodo: { nombre: string };
}

interface VoiceSessionResponse {
  conversation_id: string;
}

interface ErrorPayload {
  error?: string;
  detail?: string;
}

export class CompanionApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "CompanionApiError";
  }
}

const normalizeBase = (value: string): string =>
  value.trim().replace(/\/+$/, "");

const endpoint = (settings: Pick<CompanionSettings, "apiBase">, path: string) =>
  `${normalizeBase(settings.apiBase)}${path}`;

const parseError = async (response: Response): Promise<string> => {
  try {
    const payload = (await response.json()) as ErrorPayload;
    return payload.error || payload.detail || `La petición falló (${response.status})`;
  } catch {
    return `La petición falló (${response.status})`;
  }
};

const ensureOk = async (response: Response): Promise<Response> => {
  if (!response.ok) {
    throw new CompanionApiError(response.status, await parseError(response));
  }
  return response;
};

export function loadCompanionSettings(): CompanionSettings | null {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<CompanionSettings>;
    if (!value.apiBase || !value.nodeToken || !value.nodeName) return null;
    return {
      apiBase: normalizeBase(value.apiBase),
      nodeToken: value.nodeToken,
      nodeName: value.nodeName,
    };
  } catch {
    return null;
  }
}

export function saveCompanionSettings(settings: CompanionSettings): void {
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

export function clearCompanionSettings(): void {
  window.localStorage.removeItem(SETTINGS_KEY);
}

export async function registerCompanion(input: {
  apiBase: string;
  name: string;
  password: string;
  nodeName: string;
}): Promise<CompanionSettings> {
  const base = normalizeBase(input.apiBase);
  const response = await ensureOk(
    await fetch(`${base}/api/auth/nodos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nombre: input.name,
        contraseña: input.password,
        nodo: input.nodeName,
        plataforma: "windows-companion",
      }),
    }),
  );
  const result = (await response.json()) as RegisterNodeResponse;
  return {
    apiBase: base,
    nodeToken: result.token,
    nodeName: result.nodo.nombre,
  };
}

const authorization = (settings: CompanionSettings): Record<string, string> => ({
  Authorization: `Bearer ${settings.nodeToken}`,
});

export async function sendCompanionVoice(
  settings: CompanionSettings,
  blob: Blob,
  filename: string,
  conversationId: string,
  signal: AbortSignal,
): Promise<VoiceResponse> {
  const body = new FormData();
  body.append("audio", blob, filename);
  body.append("client_ref", `desktop-${crypto.randomUUID()}`);
  body.append("conversation_mode", "true");
  body.append("conversation_id", conversationId);
  const response = await ensureOk(
    await fetch(endpoint(settings, "/api/voz"), {
      method: "POST",
      headers: authorization(settings),
      body,
      signal,
    }),
  );
  return (await response.json()) as VoiceResponse;
}

export async function openCompanionConversation(
  settings: CompanionSettings,
): Promise<string> {
  const response = await ensureOk(
    await fetch(endpoint(settings, "/api/voz/abrir"), {
      method: "POST",
      headers: authorization(settings),
    }),
  );
  const result = (await response.json()) as VoiceSessionResponse;
  return result.conversation_id;
}

export async function closeCompanionConversation(
  settings: CompanionSettings,
  conversationId?: string,
): Promise<void> {
  await ensureOk(
    await fetch(endpoint(settings, "/api/voz/cerrar"), {
      method: "POST",
      headers: conversationId
        ? {
            ...authorization(settings),
            "Content-Type": "application/json",
          }
        : authorization(settings),
      body: conversationId
        ? JSON.stringify({ conversation_id: conversationId })
        : undefined,
    }),
  );
}

export async function requestCompanionSpeech(
  settings: CompanionSettings,
  text: string,
  signal: AbortSignal,
): Promise<Blob> {
  const response = await ensureOk(
    await fetch(endpoint(settings, "/api/tts"), {
      method: "POST",
      headers: {
        ...authorization(settings),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ texto: text }),
      signal,
    }),
  );
  return response.blob();
}

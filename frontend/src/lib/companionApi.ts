import { setApiBase } from "./api";
import { clearToken, setToken } from "./auth";
import type { VoiceResponse } from "../types";

const SETTINGS_KEY = "vibi.companion.settings";
const LEGACY_SETTINGS_KEY = "morgana.companion.settings";

export interface CompanionSettings {
  apiBase: string;
  nodeToken: string;
  nodeName: string;
  /**
   * JWT de usuario, para todo lo que no sea voz.
   *
   * El token de nodo deliberadamente NO sirve aquí: vive en el disco de esta
   * máquina y solo vale para voz y TTS. Si diera acceso a la API entera, quien
   * lo robara podría aprobar las órdenes que él mismo pide, y el permiso que
   * te pedimos antes de ejecutar algo dejaría de significar nada.
   *
   * Opcional porque un companion vinculado antes de esta versión no lo tiene:
   * seguirá hablando por voz y pedirá la contraseña para lo demás.
   */
  userToken?: string;
  /** Con quién iniciar sesión cuando el JWT caduque, para no preguntarlo. */
  userName?: string;
}

interface RegisterNodeResponse {
  token: string;
  nodo: { nombre: string };
}

interface LoginResponse {
  token: string;
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
    const current = window.localStorage.getItem(SETTINGS_KEY);
    const raw = current ?? window.localStorage.getItem(LEGACY_SETTINGS_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<CompanionSettings>;
    if (!value.apiBase || !value.nodeToken || !value.nodeName) return null;
    const settings = {
      apiBase: normalizeBase(value.apiBase),
      nodeToken: value.nodeToken,
      nodeName: value.nodeName,
      userToken: value.userToken,
      userName: value.userName,
    };
    if (!current) {
      window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    }
    return settings;
  } catch {
    return null;
  }
}

export function saveCompanionSettings(settings: CompanionSettings): void {
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  applyCompanionSession(settings);
}

export function clearCompanionSettings(): void {
  window.localStorage.removeItem(SETTINGS_KEY);
  window.localStorage.removeItem(LEGACY_SETTINGS_KEY);
  clearToken();
}

/**
 * Olvida solo el JWT caducado y deja intacta la vinculación de voz.
 *
 * Si el token muerto siguiera guardado, al arrancar se volvería a instalar y
 * el companion repetiría el mismo 401 en cada sesión sin decir nunca por qué.
 */
export function forgetCompanionUserToken(): void {
  const settings = loadCompanionSettings();
  clearToken();
  if (!settings?.userToken) return;
  delete settings.userToken;
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

/**
 * Enseña al cliente HTTP compartido con la PWA dónde vive Vibi y con qué
 * credencial hablarle.
 *
 * La PWA se sirve desde el propio servidor y saca el token de `localStorage`;
 * el companion es una ventana Tauri con otro origen y con su propio almacén,
 * así que hay que puentear las dos cosas antes de la primera petición.
 */
export function applyCompanionSession(
  settings: CompanionSettings | null = loadCompanionSettings(),
): void {
  if (!settings) return;
  setApiBase(settings.apiBase);
  if (settings.userToken) setToken(settings.userToken);
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

  // Segunda credencial, con la misma contraseña que ya tenemos en la mano: un
  // JWT normal de usuario para bandeja, archivos y aprobaciones. Caduca a los
  // 30 días y entonces se vuelve a pedir la contraseña, igual que en la PWA.
  const sesion = await ensureOk(
    await fetch(`${base}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre: input.name, contraseña: input.password }),
    }),
  );
  const { token: userToken } = (await sesion.json()) as LoginResponse;

  return {
    apiBase: base,
    nodeToken: result.token,
    nodeName: result.nodo.nombre,
    userToken,
    userName: input.name,
  };
}

/**
 * Consigue el JWT de usuario sin deshacer la vinculación de voz.
 *
 * Hace falta en dos momentos: un companion vinculado antes de que la consola
 * existiera nunca llegó a pedirlo, y a los treinta días el JWT caduca. En los
 * dos casos la voz sigue funcionando —va con el token de nodo— y lo único que
 * falta es la contraseña, así que no tiene sentido pedir el servidor y el
 * nombre del PC otra vez.
 */
export async function connectCompanionConsole(input: {
  name: string;
  password: string;
}): Promise<CompanionSettings> {
  const settings = loadCompanionSettings();
  if (!settings) {
    throw new CompanionApiError(400, "Este PC todavía no está vinculado.");
  }
  const response = await ensureOk(
    await fetch(endpoint(settings, "/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre: input.name, contraseña: input.password }),
    }),
  );
  const { token } = (await response.json()) as LoginResponse;
  const actualizado: CompanionSettings = {
    ...settings,
    userToken: token,
    userName: input.name,
  };
  saveCompanionSettings(actualizado);
  return actualizado;
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
  // Identifica el turno en el canal de eventos: es lo que deja a la cara ir
  // locutando lo que Vibi escribe sin esperar a que termine el turno.
  clientRef: string = `desktop-${crypto.randomUUID()}`,
): Promise<VoiceResponse> {
  const body = new FormData();
  body.append("audio", blob, filename);
  body.append("client_ref", clientRef);
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

import { clearToken, getToken } from "./auth";

/**
 * Dónde vive Vibi. La PWA se sirve desde el propio servidor y le basta con
 * rutas relativas; el companion es una ventana Tauri cuyo origen no es el
 * servidor, así que necesita la URL completa que guardó al vincularse.
 */
let apiBase = "";

export const setApiBase = (base: string): void => {
  apiBase = base.trim().replace(/\/+$/, "");
};

export const getApiBase = (): string => apiBase;

/** Convierte una ruta de la API en la URL absoluta que toque en cada cliente. */
export const apiUrl = (path: string): string => `${apiBase}${path}`;

/** La misma base, pero para abrir el WebSocket de eventos. */
export const websocketUrl = (path: string): string => {
  if (apiBase) return `${apiBase.replace(/^http/, "ws")}${path}`;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
};

interface ErrorPayload {
  error?: string;
  detail?: string;
}

const errorMessage = (payload: ErrorPayload, status: number) =>
  payload?.error || payload?.detail || `La petición falló (${status})`;

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const readPayload = async (response: Response): Promise<unknown> => {
  if (response.status === 204) return undefined;
  const type = response.headers.get("Content-Type") ?? "";
  if (type.includes("application/json")) return response.json();
  return response.text();
};

const authenticatedFetch = async (
  path: string,
  init: RequestInit,
): Promise<Response> => {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(apiUrl(path), { ...init, headers });
  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent("vibi:unauthorized"));
    // El companion no tiene rutas ni pantalla de login: avisa por el evento y
    // deja que decida él qué enseñar.
    if (!apiBase && window.location.pathname !== "/login") {
      window.history.replaceState({}, "", "/login");
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  }
  return response;
};

const throwResponseError = async (response: Response): Promise<never> => {
  const payload = (await readPayload(response)) as ErrorPayload;
  throw new ApiError(
    response.status,
    errorMessage(payload, response.status),
  );
};

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await authenticatedFetch(path, init);
  const payload = await readPayload(response);
  if (!response.ok) {
    const error = payload as ErrorPayload;
    throw new ApiError(
      response.status,
      errorMessage(error, response.status),
    );
  }
  return payload as T;
}

export async function apiBlob(
  path: string,
  init: RequestInit = {},
): Promise<Blob> {
  const response = await authenticatedFetch(path, init);
  if (!response.ok) return throwResponseError(response);
  return response.blob();
}

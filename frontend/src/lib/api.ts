import { clearToken, getToken } from "./auth";

interface ErrorPayload {
  error?: string;
}

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
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent("morgana:unauthorized"));
    if (window.location.pathname !== "/login") {
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
    payload?.error || `La petición falló (${response.status})`,
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
      error?.error || `La petición falló (${response.status})`,
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

import type { Draft } from "./types";
import { DEMO_MODE, PREVIEW_WRITE_MESSAGE } from "./demo/config";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const USER_KEY = "mb_user";
const PATIENT_KEY = "mb_patient";

function stored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string | null) {
  try {
    if (value) window.localStorage.setItem(key, value);
    else window.localStorage.removeItem(key);
  } catch {
    // private window: the choice lasts until reload
  }
}

export const session = {
  user: () => stored(USER_KEY),
  patient: () => stored(PATIENT_KEY),
  setUser: (id: string | null) => store(USER_KEY, id),
  setPatient: (id: string | null) => store(PATIENT_KEY, id),
};

const BACKEND_UNREACHABLE =
  "Cannot reach the backend API. Start the FastAPI server (uvicorn app.main:app --port 8000) and refresh.";

// UI-preview builds answer from bundled synthetic fixtures and never reach the network.
async function previewRequest<T>(path: string, options: RequestInit): Promise<T> {
  const { mockRequest } = await import("./demo/mockApi");
  try {
    return (await mockRequest(options.method || "GET", path)) as T;
  } catch (error: any) {
    throw new ApiError(error?.message || "UI preview error", error?.status || 500);
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (DEMO_MODE) return previewRequest<T>(path, options);
  const headers = new Headers(options.headers || {});
  const user = session.user();
  const patient = session.patient();
  if (user) headers.set("X-User-Id", user);
  if (patient) headers.set("X-Patient-Id", patient);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...options, headers });
  } catch {
    throw new ApiError(BACKEND_UNREACHABLE, 0);
  }
  if (!response.ok) {
    let detail = response.statusText;
    let fromBackend = false;
    try {
      const data = await response.json();
      fromBackend = true;
      detail = data.detail || detail;
      if (Array.isArray(detail)) {
        detail = detail.map((item: any) => item.msg || JSON.stringify(item)).join("; ");
      }
    } catch {
      // keep status text
    }
    // A non-JSON 5xx comes from the dev proxy when the FastAPI server is not running.
    if (!fromBackend && response.status >= 500) detail = BACKEND_UNREACHABLE;
    throw new ApiError(String(detail), response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, body?: any) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(path: string, body: any) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });

/** Opens a server-rendered page (print view, review pack). The preview serves static copies only. */
export function openApiWindow(path: string) {
  if (!DEMO_MODE) {
    window.open(`/api${path}`, "_blank");
    return;
  }
  if (path === "/revenue/claim-prep/pack.html") {
    window.open("/demo/claim-pack.html", "_blank");
    return;
  }
  window.alert(PREVIEW_WRITE_MESSAGE);
}

export async function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  return api<any>("/documents/upload", { method: "POST", body: form });
}

export async function transcribeAudio(blob: Blob, filename = "consultation.webm") {
  const form = new FormData();
  form.append("file", blob, filename);
  const receipt = await api<{ audio_id: string; status: string }>("/notes/transcribe", { method: "POST", body: form });
  // The MediBytes pipeline answers with a receipt; poll until the note is ready (usually under a minute).
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    const status = await api<{ status: string; error?: string; draft?: Draft }>(`/notes/transcribe/${encodeURIComponent(receipt.audio_id)}`);
    if (status.status === "succeeded" && status.draft) return { draft: status.draft };
    if (status.status === "failed") throw new Error(status.error || "The recording could not be processed");
  }
  throw new Error("The pipeline is taking too long. Try again in a minute.");
}

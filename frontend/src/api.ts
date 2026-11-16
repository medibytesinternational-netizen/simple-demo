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

/**
 * A stored file (signed OPD note or uploaded report) as a local object URL. Fetched with the
 * session headers, because a plain link would not say which patient is open.
 */
export async function storedFileUrl(documentId: string): Promise<string> {
  if (DEMO_MODE) throw new ApiError(PREVIEW_WRITE_MESSAGE, 403);
  const headers = new Headers();
  const user = session.user();
  const patient = session.patient();
  if (user) headers.set("X-User-Id", user);
  if (patient) headers.set("X-Patient-Id", patient);
  let response: Response;
  try {
    response = await fetch(`/api/documents/${encodeURIComponent(documentId)}/file`, { headers });
  } catch {
    throw new ApiError(BACKEND_UNREACHABLE, 0);
  }
  if (!response.ok) throw new ApiError(response.status === 404 ? "The stored document was not found." : response.statusText, response.status);
  return URL.createObjectURL(await response.blob());
}

/** Opens a stored document in a new tab, where it can be read and printed. */
export async function openStoredFile(documentId: string) {
  // Open the tab first, inside the click, so pop-up blockers allow it; fill it once the file arrives.
  const tab = window.open("", "_blank");
  try {
    const url = await storedFileUrl(documentId);
    if (tab) tab.location.href = url;
    else window.open(url, "_blank");
  } catch (error) {
    tab?.close();
    throw error;
  }
}

export async function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  return api<any>("/documents/upload", { method: "POST", body: form });
}

/** What intake read from a recording or an old document, for the new patient form. */
export type IntakeField = { value: any; confidence: number; source: string };
export type Intake = {
  intake_id: string;
  kind: "audio" | "document";
  filename: string;
  status: "pending" | "running" | "ready" | "failed";
  fields: Record<string, IntakeField>;
  method?: string | null;
  error?: string | null;
  doc_type?: string | null;
  /** Recording: the OPD report in the hospital format, shown before saving. */
  preview?: Record<string, any> | null;
  /** Document: values read from it (medicines, results). */
  values?: { name: string; value: string; unit: string; reference_range: string }[];
};

export async function intakeDocument(file: File, docType: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", docType);
  return api<Intake>("/intake/document", { method: "POST", body: form });
}

/** Sends the consented consultation recording and waits until its details have been read. */
export async function intakeAudio(blob: Blob, filename = "consultation.webm") {
  const form = new FormData();
  form.append("file", blob, filename);
  form.append("consent", "true");
  const receipt = await api<Intake>("/intake/audio", { method: "POST", body: form });
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    const status = await api<Intake>(`/intake/${encodeURIComponent(receipt.intake_id)}`);
    if (status.status === "ready") return status;
    if (status.status === "failed") throw new Error(status.error || "The recording could not be processed");
  }
  throw new Error("The pipeline is taking too long. Try again in a minute.");
}

export async function transcribeAudio(blob: Blob, filename = "consultation.webm", feature = "F1") {
  const form = new FormData();
  form.append("file", blob, filename);
  form.append("feature", feature);
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

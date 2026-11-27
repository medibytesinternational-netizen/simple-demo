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
  note_content?: MediBytesNote | null;
  needs_review?: NeedsReview[];
  /** Document: values read from it (medicines, results). */
  values?: { name: string; value: string; unit: string; reference_range: string }[];
};

export type MediBytesNote = {
  present_illness: string;
  examination_findings: string;
  previous_diagnosis: string;
  plan_of_management: string;
  diet_instructions: string;
  general_instructions: string;
};
export type NeedsReview = { section: string; text: string };
export type TranscriptionJob = {
  audio_id: string;
  intake_id?: string | null;
  encounter_id: string;
  feature: string;
  role?: string | null;
  filename: string;
  job_status: "queued" | "running" | "succeeded" | "failed";
  job_error?: string | null;
  delivery: {
    state: "pending" | "delivered" | "failed" | "job_failed";
    attempts: number;
    last_error?: string | null;
    next_attempt_at?: string | null;
  };
  transcript?: string | null;
  note_content?: MediBytesNote | null;
  needs_review?: NeedsReview[];
  response?: string | null;
  transcript_event_id?: string | null;
  draft_id?: string | null;
  draft?: Draft | null;
  can_redeliver?: boolean;
  can_retry_upload?: boolean;
  status_check_error?: string | null;
};

export async function intakeDocument(file: File, docType: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", docType);
  return api<Intake>("/intake/document", { method: "POST", body: form });
}

const TRANSCRIPTION_POLL_MS = 15_000;
const TRANSCRIPTION_MAX_POLLS = 180;

/** Sends the consented intake recording through the same backend MediBytes client. */
export async function intakeAudio(blob: Blob, filename = "consultation.webm") {
  const form = new FormData();
  form.append("file", blob, filename);
  form.append("consent", "true");
  const receipt = await api<Intake>("/intake/audio", { method: "POST", body: form });
  for (let attempt = 0; attempt < TRANSCRIPTION_MAX_POLLS; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, TRANSCRIPTION_POLL_MS));
    const status = await api<Intake>(`/intake/${encodeURIComponent(receipt.intake_id)}`);
    if (status.status === "ready") return status;
    if (status.status === "failed") throw new Error(status.error || "The recording could not be processed");
  }
  throw new Error("MediBytes is still processing the intake recording. Check the intake again shortly.");
}

/** Submit any encounter recording to the single /notes/transcribe route. */
export async function transcribeAudio(
  blob: Blob,
  filename: string,
  encounterId: string,
  audioId: string,
  feature = "F1",
  role = "",
) {
  const form = new FormData();
  form.append("file", blob, filename);
  form.append("feature", feature);
  if (role) form.append("role", role);
  return api<TranscriptionJob>(
    `/notes/transcribe?encounter_id=${encodeURIComponent(encounterId)}&audio_id=${encodeURIComponent(audioId)}`,
    { method: "POST", body: form },
  );
}

export async function activeEncounterId() {
  const meta = await get<{ encounter: { id: string } }>("/meta");
  return meta.encounter.id;
}

export function getTranscription(audioId: string, encounterId: string) {
  return get<TranscriptionJob>(
    `/notes/transcriptions/${encodeURIComponent(audioId)}?encounter_id=${encodeURIComponent(encounterId)}`,
  );
}

export async function waitForTranscription(audioId: string, encounterId: string) {
  for (let attempt = 0; attempt < TRANSCRIPTION_MAX_POLLS; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, TRANSCRIPTION_POLL_MS));
    const status = await getTranscription(audioId, encounterId);
    if (status.job_status === "failed") throw new Error(status.job_error || "The recording could not be processed");
    if (status.job_status === "succeeded" && status.draft) return status;
  }
  throw new Error("MediBytes is still processing this recording. It remains attached to the consultation; check again shortly.");
}

/** Submit and wait for the feature-specific reviewable draft. */
export async function generateVoiceDraft(
  blob: Blob,
  filename: string,
  feature: string,
  role = "",
): Promise<Draft> {
  const encounterId = await activeEncounterId();
  const audioId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const submitted = await transcribeAudio(blob, filename, encounterId, audioId, feature, role);
  const completed = await waitForTranscription(submitted.audio_id, encounterId);
  if (!completed.draft) throw new Error("MediBytes completed the recording without a reviewable draft.");
  return completed.draft;
}

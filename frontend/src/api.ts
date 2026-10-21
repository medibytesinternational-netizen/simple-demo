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

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  const user = session.user();
  const patient = session.patient();
  if (user) headers.set("X-User-Id", user);
  if (patient) headers.set("X-Patient-Id", patient);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail || detail;
      if (Array.isArray(detail)) {
        detail = detail.map((item: any) => item.msg || JSON.stringify(item)).join("; ");
      }
    } catch {
      // keep status text
    }
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

export async function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  return api<any>("/documents/upload", { method: "POST", body: form });
}

export async function transcribeAudio(blob: Blob, filename = "consultation.webm") {
  const form = new FormData();
  form.append("file", blob, filename);
  return api<{ text: string; model: string }>("/notes/transcribe", { method: "POST", body: form });
}

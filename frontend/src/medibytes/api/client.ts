import type { Health, Job, JobAccepted, JobSummary } from "./types";

/** Error raised for any failed API call. `status` is 0 when the server could not be reached. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** Network failures, rate limiting and 5xx are worth retrying; 4xx are not. */
  get transient(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException
    ? err.name === "AbortError"
    : err instanceof Error && err.name === "AbortError";
}

export interface ApiClient {
  health(signal?: AbortSignal): Promise<Health>;
  submitJob(file: File, signal?: AbortSignal): Promise<JobAccepted>;
  listJobs(signal?: AbortSignal): Promise<JobSummary[]>;
  getJob(jobId: string, signal?: AbortSignal): Promise<Job>;
  /** URL of a job artefact, suitable for <audio src> or a download link. */
  fileUrl(jobId: string, name: string): string;
}

export interface ApiClientOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}

const FALLBACK_DETAIL: Record<number, string> = {
  400: "The upload was empty or malformed.",
  404: "Not found.",
  413: "The file is too large (64 MB maximum).",
  415: "Unsupported file type.",
  429: "The server is busy. Please try again shortly.",
  500: "The server hit an internal error.",
  502: "The server is unavailable.",
  503: "The server is unavailable.",
};

/** FastAPI sends {detail: string} for HTTPException and {detail: [{msg}]} for validation errors. */
function readDetail(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body)) return null;
  const detail: unknown = body.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d: unknown) =>
        typeof d === "object" && d !== null && "msg" in d && typeof d.msg === "string" ? d.msg : null,
      )
      .filter((m): m is string => m !== null);
    if (msgs.length > 0) return msgs.join("; ");
  }
  return null;
}

async function errorFromResponse(res: Response): Promise<ApiError> {
  let detail: string | null = null;
  try {
    const text = await res.text();
    if (text) {
      try {
        detail = readDetail(JSON.parse(text) as unknown);
      } catch {
        detail = text.length <= 200 ? text : null;
      }
    }
  } catch {
    // body unreadable; fall through to a generic message
  }
  const fallback = FALLBACK_DETAIL[res.status] ?? `Request failed (HTTP ${res.status}).`;
  return new ApiError(res.status, detail ?? fallback);
}

export function createApiClient(options: ApiClientOptions = {}): ApiClient {
  const base = (options.baseUrl ?? "").replace(/\/+$/, "");
  const doFetch: typeof fetch = options.fetchImpl ?? ((input, init) => fetch(input, init));

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let res: Response;
    try {
      res = await doFetch(`${base}${path}`, {
        ...init,
        headers: { Accept: "application/json", ...init.headers },
      });
    } catch (err) {
      if (isAbortError(err)) throw err;
      throw new ApiError(0, "Could not reach the MediBytes server. Check your connection.");
    }
    if (!res.ok) throw await errorFromResponse(res);
    try {
      return (await res.json()) as T;
    } catch {
      throw new ApiError(res.status, "The server sent an unreadable response.");
    }
  }

  const jobPath = (jobId: string) => `/api/jobs/${encodeURIComponent(jobId)}`;

  return {
    health: (signal) => request<Health>("/api/health", { signal }),
    submitJob: (file, signal) => {
      const body = new FormData();
      body.append("file", file, file.name);
      return request<JobAccepted>("/api/jobs", { method: "POST", body, signal });
    },
    listJobs: (signal) => request<JobSummary[]>("/api/jobs", { signal }),
    getJob: (jobId, signal) => request<Job>(jobPath(jobId), { signal }),
    fileUrl: (jobId, name) => `${base}${jobPath(jobId)}/files/${encodeURIComponent(name)}`,
  };
}

/** Default same-origin client. Hooks take it as an overridable default so tests can inject fakes. */
const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
export const apiClient: ApiClient = createApiClient({ baseUrl: configuredBaseUrl || "" });

import { vi } from "vitest";
import type { ApiClient } from "../api/client";
import type { Health, Job, JobAccepted, JobSummary } from "../api/types";

/** In-memory ApiClient whose methods are vi.fn spies with overridable behaviour. */
export function createFakeClient(overrides: Partial<ApiClient> = {}) {
  const client = {
    health: vi.fn<(signal?: AbortSignal) => Promise<Health>>(() =>
      Promise.resolve({
        status: "ok",
        pipeline: "MedASR → small-int8 second pass → fuzzy matcher → gpt-4.1",
        llm: { model: "gpt-4.1", configured: true },
        jobs: {},
      }),
    ),
    submitJob: vi.fn<(file: File, signal?: AbortSignal) => Promise<JobAccepted>>(() =>
      Promise.resolve({ job_id: "job-1", status: "queued", status_url: "/api/jobs/job-1" }),
    ),
    listJobs: vi.fn<(signal?: AbortSignal) => Promise<JobSummary[]>>(() => Promise.resolve([])),
    getJob: vi.fn<(jobId: string, signal?: AbortSignal) => Promise<Job>>(() =>
      Promise.reject(new Error("getJob not stubbed")),
    ),
    fileUrl: vi.fn((jobId: string, name: string) => `/api/jobs/${jobId}/files/${name}`),
  };
  Object.assign(client, overrides);
  return client;
}

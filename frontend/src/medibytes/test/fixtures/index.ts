import type { Job, JobResult } from "../../api/types";
import raw from "./job.succeeded.json";

/**
 * Real pipeline output (runs/phone40/C1/s1) captured as a succeeded Job.
 * Returns a deep copy so each test can mutate freely. Test-only: never imported by app code.
 */
export function loadSucceededJob(): Job {
  return JSON.parse(JSON.stringify(raw)) as Job;
}

export function loadResult(): JobResult {
  const { result } = loadSucceededJob();
  if (!result) throw new Error("fixture has no result");
  return result;
}

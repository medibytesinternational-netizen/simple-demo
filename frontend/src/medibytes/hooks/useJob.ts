import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiClient, isAbortError, type ApiClient } from "../api/client";
import type { Job, JobStatus } from "../api/types";

export interface PollingOptions {
  /** Delay between polls while the job is queued or running. */
  intervalMs?: number;
  /** Upper bound for the exponential backoff applied after transient failures. */
  maxBackoffMs?: number;
  /** Consecutive transient failures tolerated before polling gives up. */
  maxFailures?: number;
}

export interface JobState {
  jobId: string | null;
  job: Job | null;
  /** True while the file upload request is in flight. */
  uploading: boolean;
  /** Server-provided reason the upload was refused (413/415/400 detail). */
  submitError: string | null;
  /** Polling stopped because of an unrecoverable error. */
  pollError: string | null;
  /** A poll failed transiently; the hook is backing off and will retry. */
  reconnecting: boolean;
}

export interface UseJob extends JobState {
  submit: (file: File) => Promise<void>;
  open: (jobId: string) => void;
  reset: () => void;
}

const TERMINAL: ReadonlySet<JobStatus> = new Set<JobStatus>(["succeeded", "failed"]);

export function isTerminal(status: JobStatus): boolean {
  return TERMINAL.has(status);
}

const INITIAL: JobState = {
  jobId: null,
  job: null,
  uploading: false,
  submitError: null,
  pollError: null,
  reconnecting: false,
};

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong.";
}

/**
 * Upload a dictation and follow its job until it succeeds or fails.
 * Every submit/open starts a new session; the previous one is aborted, so stale
 * responses can never overwrite newer state.
 */
export function useJob(client: ApiClient = apiClient, options: PollingOptions = {}): UseJob {
  const { intervalMs = 1000, maxBackoffMs = 16000, maxFailures = 8 } = options;
  const [state, setState] = useState<JobState>(INITIAL);

  const controllerRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => stop, [stop]);

  const poll = useCallback(
    (jobId: string, controller: AbortController) => {
      let failures = 0;

      const schedule = (delay: number) => {
        if (controller.signal.aborted) return;
        timerRef.current = setTimeout(() => {
          timerRef.current = null;
          void tick();
        }, delay);
      };

      const tick = async (): Promise<void> => {
        try {
          const job = await client.getJob(jobId, controller.signal);
          if (controller.signal.aborted) return;
          failures = 0;
          setState((s) => ({ ...s, job, reconnecting: false, pollError: null }));
          if (!isTerminal(job.status)) schedule(intervalMs);
        } catch (err) {
          if (controller.signal.aborted || isAbortError(err)) return;
          const transient = !(err instanceof ApiError) || err.transient;
          failures += 1;
          if (transient && failures <= maxFailures) {
            setState((s) => ({ ...s, reconnecting: true }));
            schedule(Math.min(intervalMs * 2 ** failures, maxBackoffMs));
            return;
          }
          setState((s) => ({ ...s, reconnecting: false, pollError: messageOf(err) }));
        }
      };

      void tick();
    },
    [client, intervalMs, maxBackoffMs, maxFailures],
  );

  const open = useCallback(
    (jobId: string) => {
      stop();
      const controller = new AbortController();
      controllerRef.current = controller;
      setState({ ...INITIAL, jobId });
      poll(jobId, controller);
    },
    [poll, stop],
  );

  const submit = useCallback(
    async (file: File) => {
      stop();
      const controller = new AbortController();
      controllerRef.current = controller;
      setState({ ...INITIAL, uploading: true });
      try {
        const accepted = await client.submitJob(file, controller.signal);
        if (controller.signal.aborted) return;
        setState({ ...INITIAL, jobId: accepted.job_id });
        poll(accepted.job_id, controller);
      } catch (err) {
        if (controller.signal.aborted || isAbortError(err)) return;
        setState({ ...INITIAL, submitError: messageOf(err) });
      }
    },
    [client, poll, stop],
  );

  const reset = useCallback(() => {
    stop();
    setState(INITIAL);
  }, [stop]);

  return { ...state, submit, open, reset };
}

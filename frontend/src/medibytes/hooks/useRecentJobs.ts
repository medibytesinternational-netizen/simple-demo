import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiClient, isAbortError, type ApiClient } from "../api/client";
import type { JobSummary } from "../api/types";

export interface RecentJobsState {
  jobs: JobSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * List recent jobs. Re-fetches whenever `refreshKey` changes (App bumps it when a
 * job is accepted or finishes) or when `refresh()` is called.
 */
export function useRecentJobs(client: ApiClient = apiClient, refreshKey: unknown = null): RecentJobsState {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const loadedOnce = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    if (!loadedOnce.current) setLoading(true);
    client
      .listJobs(controller.signal)
      .then((list) => {
        loadedOnce.current = true;
        setJobs(list);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted || isAbortError(err)) return;
        setError(err instanceof ApiError ? err.detail : "Could not load recent jobs.");
        setLoading(false);
      });
    return () => controller.abort();
  }, [client, refreshKey, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  return { jobs, loading, error, refresh };
}

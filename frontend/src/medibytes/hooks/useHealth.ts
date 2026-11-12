import { useEffect, useState } from "react";
import { ApiError, apiClient, isAbortError, type ApiClient } from "../api/client";
import type { Health } from "../api/types";

export interface HealthState {
  health: Health | null;
  error: string | null;
  loading: boolean;
}

/** Fetch /api/health once on mount. */
export function useHealth(client: ApiClient = apiClient): HealthState {
  const [state, setState] = useState<HealthState>({ health: null, error: null, loading: true });

  useEffect(() => {
    const controller = new AbortController();
    client
      .health(controller.signal)
      .then((health) => setState({ health, error: null, loading: false }))
      .catch((err: unknown) => {
        if (controller.signal.aborted || isAbortError(err)) return;
        const error = err instanceof ApiError ? err.detail : "Server unreachable.";
        setState({ health: null, error, loading: false });
      });
    return () => controller.abort();
  }, [client]);

  return state;
}

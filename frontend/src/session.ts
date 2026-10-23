import { useQuery } from "@tanstack/react-query";
import { get } from "./api";
import type { Meta } from "./types";

/** True when the acting user may do `action` (the server enforces this too). With one role this is
 * true for every action the doctor holds; only `ingest` (the hospital system link's) is false. */
export function useCan(action: string): boolean {
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  return !!meta.data?.allowed_actions?.includes(action);
}

/** The acting user's role. Always "doctor" while there is one staff role; no page branches on it. */
export function useRole(): string {
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  return meta.data?.user?.role ?? "";
}

/** The patient currently open: Ravi, the one browsable patient. */
export function usePatientId(): string {
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  return meta.data?.patient.id ?? "";
}

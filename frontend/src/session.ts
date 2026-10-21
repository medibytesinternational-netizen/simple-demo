import { useQuery } from "@tanstack/react-query";
import { get } from "./api";
import type { Meta } from "./types";

/** True when the signed-in role may do `action` (the server enforces this too). */
export function useCan(action: string): boolean {
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  return !!meta.data?.allowed_actions?.includes(action);
}

export function useRole(): string {
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  return meta.data?.user?.role ?? "";
}

/** The patient currently open in the header. */
export function usePatientId(): string {
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  return meta.data?.patient.id ?? "";
}

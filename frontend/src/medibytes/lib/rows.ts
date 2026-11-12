import type { TextRow } from "../api/types";

/**
 * Vitals heard only by the small-int8 second pass carry `second_pass` on the wire,
 * though the TextRow contract does not declare it. Read it safely.
 */
export function secondPassOf(row: TextRow): string | null {
  if (!("second_pass" in row)) return null;
  const value: unknown = row.second_pass;
  return typeof value === "string" && value ? value : null;
}

/** Answer of GET /api/integrations/status. */
export type IntegrationStatus = {
  configured: boolean;
  host: string;
  last_sync_at: string | null;
  last_sync_status: "ok" | "partial" | "failed" | null;
  queued: number;
  failed: number;
  not_configured: number;
  banner: string;
};

/** Which existing banner style fits the link's state. */
export function bannerTone(status: IntegrationStatus): "success" | "warning" | "danger" {
  if (status.failed > 0 || status.last_sync_status === "failed") return "danger";
  if (!status.configured || status.queued > 0 || status.not_configured > 0) return "warning";
  return "success";
}

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../api";
import { Icon } from "../../components/icons";
import { Modal } from "../../components/Modal";
import { bannerTone } from "./types";
import type { IntegrationStatus } from "./types";

/**
 * Compact hospital-system status in the header. The full message, host and
 * queue counts live in a small dialog so a routine page never starts with a
 * wide warning strip.
 */
export default function IntegrationBanner() {
  const [open, setOpen] = useState(false);
  const status = useQuery<IntegrationStatus>({
    queryKey: ["integration-status"],
    queryFn: () => get<IntegrationStatus>("/integrations/status"),
    refetchInterval: 30000,
  });
  if (!status.data) return null;
  const tone = bannerTone(status.data);
  const short = status.data.configured ? "Hospital link" : "No hospital link";
  const when = status.data.last_sync_at
    ? new Date(status.data.last_sync_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : "Never synced";

  return (
    <>
      <button type="button" className={`chrome-btn integration-chip ${tone}`} onClick={() => setOpen(true)}
        aria-haspopup="dialog" aria-label={`Integration status: ${status.data.banner}`} title={status.data.banner}
        data-testid="integration-banner">
        <Icon name={tone === "success" ? "check" : "alert"} size={16} />
        <span className="integration-chip-text">{short}</span>
      </button>
      {open ? (
        <Modal title="Hospital system link" onClose={() => setOpen(false)}
          footer={<button type="button" className="btn" onClick={() => setOpen(false)}>Close</button>}>
          <p className={`banner ${tone}`} role="status" style={{ marginTop: 0 }}>{status.data.banner}</p>
          <dl className="kv mt-3">
            <dt>Host</dt><dd>{status.data.host || "Not configured"}</dd>
            <dt>Last sync</dt><dd>{when}</dd>
            <dt>Status</dt><dd>{status.data.last_sync_status || "No completed sync"}</dd>
            <dt>Queued</dt><dd>{status.data.queued}</dd>
            <dt>Failed</dt><dd>{status.data.failed}</dd>
            <dt>Not configured</dt><dd>{status.data.not_configured}</dd>
          </dl>
          <p className="small muted mt-3">This demo does not send records to an external hospital system.</p>
        </Modal>
      ) : null}
    </>
  );
}

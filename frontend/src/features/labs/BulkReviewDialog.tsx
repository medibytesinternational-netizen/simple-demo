import { useState } from "react";
import { ApiError, post } from "../../api";
import type { Lab } from "../../types";
import { Modal } from "../../components/Modal";
import { Banner } from "../../components/ui";
import { isBulkReviewable } from "./labStatus";

type Outcome = {
  done: Lab[];
  failed: { lab: Lab; message: string }[];
  notAttempted: Lab[];
};

/**
 * Marks several normal results reviewed with the existing single-result endpoint, one call at a
 * time, so each result gets its own audit entry. There is no bulk endpoint on the server.
 */
export function BulkReviewDialog({ labs, onClose, onFinished }: {
  /** Taken when the dialog opens; only unreviewed results flagged normal are used. */
  labs: Lab[];
  onClose: () => void;
  /** Called once when at least one result was marked, so the page can refresh. */
  onFinished: () => void;
}) {
  const [items] = useState(() => labs.filter(isBulkReviewable));
  const [running, setRunning] = useState(false);
  const [current, setCurrent] = useState(0);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const run = async () => {
    setRunning(true);
    const result: Outcome = { done: [], failed: [], notAttempted: [] };
    for (let i = 0; i < items.length; i += 1) {
      const lab = items[i];
      setCurrent(i + 1);
      try {
        await post(`/labs/${lab.event_id}/review`);
        result.done.push(lab);
      } catch (err) {
        const error = err as ApiError;
        result.failed.push({ lab, message: String(error?.message || error) });
        // Not allowed (or the preview) and an unreachable server fail the same way for every result: stop.
        if (error?.status === 403 || error?.status === 0) {
          result.notAttempted = items.slice(i + 1);
          break;
        }
      }
    }
    setOutcome(result);
    setRunning(false);
    if (result.done.length) onFinished();
  };

  const close = () => {
    if (!running) onClose();
  };

  const footer = outcome ? (
    <button type="button" className="btn btn-primary" onClick={onClose}>Close</button>
  ) : (
    <>
      <button type="button" className="btn" onClick={close} disabled={running}>Cancel</button>
      <button type="button" className="btn btn-primary" onClick={run} disabled={running || !items.length} aria-busy={running || undefined}>
        {running ? <><span className="spinner" /> Reviewing {current} of {items.length}…</> : `Mark ${items.length} normal result${items.length === 1 ? "" : "s"} reviewed`}
      </button>
    </>
  );

  return (
    <Modal title="Review normal results" onClose={close} footer={footer} width={520}>
      {outcome ? (
        <div className="labs-bulk-outcome" role="status">
          {outcome.failed.length === 0 ? (
            <Banner tone="success">Marked {outcome.done.length} normal result{outcome.done.length === 1 ? "" : "s"} reviewed.</Banner>
          ) : (
            <Banner tone={outcome.done.length ? "warning" : "danger"} title={`Marked ${outcome.done.length} of ${items.length} reviewed`}>
              The results below were not marked and stay unreviewed.
            </Banner>
          )}
          {outcome.failed.length ? (
            <ul className="labs-bulk-list">
              {outcome.failed.map(({ lab, message }) => (
                <li key={lab.event_id}><strong>{lab.name}</strong>: {message}</li>
              ))}
              {outcome.notAttempted.map((lab) => (
                <li key={lab.event_id}><strong>{lab.name}</strong>: not attempted</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <>
          <p className="labs-bulk-lead">
            These results are flagged <strong>normal</strong> by their source and have not been reviewed.
            Each one is marked reviewed separately and audited in your name.
          </p>
          <ul className="labs-bulk-list">
            {items.map((lab) => (
              <li key={lab.event_id}>
                <strong>{lab.name}</strong> <span className="mono">{lab.value} {lab.unit}</span>
                <span className="muted"> · ref {lab.reference_range || "not given"}</span>
              </li>
            ))}
          </ul>
          <p className="small muted">Abnormal and unflagged results are not included; review those one at a time.</p>
        </>
      )}
    </Modal>
  );
}

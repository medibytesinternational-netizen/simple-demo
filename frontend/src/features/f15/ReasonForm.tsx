import { useState } from "react";
import { useId } from "react";
import { reasonOk } from "./rules";
import { MIN_REASON } from "./types";
import type { ReasonMode } from "./types";

const COPY: Record<ReasonMode, { label: string; confirm: string }> = {
  escalate: { label: "Why does this need escalating?", confirm: "Escalate" },
  reopen: { label: "Why is this task being reopened?", confirm: "Reopen" },
};

export function ReasonForm({
  mode,
  busy,
  onConfirm,
  onCancel,
}: {
  mode: ReasonMode;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const copy = COPY[mode];
  const inputId = useId();
  const typed = reason.trim().length;
  return (
    <div className="reason-form" role="group" aria-label={copy.label}>
      <div className="form-field reason-field">
        <label className="field-label" htmlFor={inputId}>{copy.label}</label>
        <input
          id={inputId}
          className="input"
          value={reason}
          autoFocus
          placeholder={`At least ${MIN_REASON} characters`}
          aria-describedby={`${inputId}-hint`}
          onChange={(event) => setReason(event.target.value)}
        />
        <div className="field-hint" id={`${inputId}-hint`}>
          {typed >= MIN_REASON ? "Recorded in the audit log with your name." : `${typed} of ${MIN_REASON} characters minimum.`}
        </div>
      </div>
      <div className="button-row reason-actions">
        <button type="button" className="btn btn-sm btn-primary" disabled={!reasonOk(reason) || busy} aria-busy={busy || undefined} onClick={() => onConfirm(reason.trim())}>
          {busy ? <span className="spinner" /> : null}
          {copy.confirm}
        </button>
        <button type="button" className="btn btn-sm btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

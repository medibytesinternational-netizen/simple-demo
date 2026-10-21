import { useState } from "react";
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
  return (
    <div className="form-row" style={{ alignItems: "flex-end" }}>
      <div style={{ flex: 1, minWidth: 260 }}>
        <label className="field-label">{copy.label}</label>
        <input
          className="input"
          value={reason}
          autoFocus
          placeholder={`At least ${MIN_REASON} characters`}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <button className="btn btn-sm btn-primary" disabled={!reasonOk(reason) || busy} onClick={() => onConfirm(reason.trim())}>
        {copy.confirm}
      </button>
      <button className="btn btn-sm btn-ghost" onClick={onCancel}>Cancel</button>
    </div>
  );
}

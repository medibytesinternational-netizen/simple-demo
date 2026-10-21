import { DISMISS_CATEGORIES, MIN_REASON } from "./types";
import type { DismissCategory } from "./types";

type Props = {
  category: DismissCategory | "";
  reason: string;
  onCategory: (value: DismissCategory | "") => void;
  onReason: (value: string) => void;
};

export function dismissReady(category: DismissCategory | "", reason: string): boolean {
  return category !== "" && reason.trim().length >= MIN_REASON;
}

export function DismissFields({ category, reason, onCategory, onReason }: Props) {
  const missing = MIN_REASON - reason.trim().length;
  return (
    <>
      <label className="field-label">Why is it being dismissed? (required)</label>
      <select
        className="input mb-2"
        value={category}
        onChange={(event) => onCategory(event.target.value as DismissCategory | "")}
      >
        <option value="">Choose one…</option>
        {DISMISS_CATEGORIES.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
      <label className="field-label">Reason (required, audited)</label>
      <textarea
        className="textarea small"
        value={reason}
        onChange={(event) => onReason(event.target.value)}
        placeholder="Say what you checked or decided."
      />
      {reason && missing > 0 ? <div className="small muted mt-1">{missing} more characters required.</div> : null}
    </>
  );
}

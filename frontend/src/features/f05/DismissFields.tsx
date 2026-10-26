import { DISMISS_CATEGORIES, MIN_REASON } from "./types";
import type { DismissCategory } from "./types";
import { Field } from "../../components/ui";

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
    <div className="flex-col gap-3">
      <Field label="Why is it being dismissed?" htmlFor="dismiss-category" required>
        <select
          id="dismiss-category"
          className="input"
          value={category}
          onChange={(event) => onCategory(event.target.value as DismissCategory | "")}
        >
          <option value="">Choose one…</option>
          {DISMISS_CATEGORIES.map((item) => (
            <option key={item.value} value={item.value}>{item.label}</option>
          ))}
        </select>
      </Field>
      <Field
        label="Reason (audited)"
        htmlFor="dismiss-reason"
        required
        hint={reason && missing > 0 ? `${missing} more characters required.` : undefined}
      >
        <textarea
          id="dismiss-reason"
          className="textarea small"
          value={reason}
          onChange={(event) => onReason(event.target.value)}
          placeholder="Say what you checked or decided."
        />
      </Field>
    </div>
  );
}

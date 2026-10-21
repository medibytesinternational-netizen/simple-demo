import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../../api";
import type { ManualFieldInput } from "./types";

const EMPTY: ManualFieldInput = { name: "", value: "", unit: "", reference_range: "", collected_at: "" };

export function ManualEntryForm({
  documentId,
  docType,
  allowed,
  onError,
}: {
  documentId: string;
  docType: string;
  allowed: boolean;
  onError: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ManualFieldInput>(EMPTY);
  const isRx = docType === "prescription";
  const isText = docType === "radiology_report" || docType === "discharge_summary";
  const add = useMutation({
    mutationFn: () => post(`/documents/${documentId}/fields`, form),
    onSuccess: () => {
      onError("");
      setForm(EMPTY);
      queryClient.invalidateQueries();
    },
    onError: (err: any) => onError(String(err?.message || err)),
  });
  const set = (key: keyof ManualFieldInput) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <div className="field-row" style={{ borderTop: "1px solid var(--border)", marginTop: 8, paddingTop: 8 }}>
      <div className="field-name">Type a value from the original</div>
      <div className="small muted">What you type is saved as confirmed by you and marked as typed by hand.</div>
      <div className="flex gap-2 mt-1" style={{ flexWrap: "wrap" }}>
        <input
          className="input"
          placeholder={isRx ? "Medicine" : isText ? "Heading (Impression, Findings)" : "Test name"}
          value={form.name}
          onChange={set("name")}
          style={{ width: 170 }}
        />
        <input
          className="input"
          placeholder={isRx ? "Dose" : isText ? "Text" : "Result"}
          value={form.value}
          onChange={set("value")}
          style={{ width: isText ? 260 : 100 }}
        />
        {!isText && !isRx ? (
          <input className="input" placeholder="Unit" value={form.unit} onChange={set("unit")} style={{ width: 90 }} />
        ) : null}
        {!isText ? (
          <input
            className="input"
            placeholder={isRx ? "How often" : "Reference range"}
            value={form.reference_range}
            onChange={set("reference_range")}
            style={{ width: 130 }}
          />
        ) : null}
        {!isText && !isRx ? (
          <input
            className="input"
            type="date"
            aria-label="Collected on"
            value={form.collected_at}
            onChange={set("collected_at")}
            style={{ width: 140 }}
          />
        ) : null}
        <button
          className="btn btn-sm"
          onClick={() => add.mutate()}
          disabled={!allowed || add.isPending || !form.name.trim() || !form.value.trim()}
        >
          {add.isPending ? "Saving…" : "Add value"}
        </button>
      </div>
      {!allowed ? <div className="small muted mt-1">Your role cannot enter values.</div> : null}
    </div>
  );
}

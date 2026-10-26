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
    <div className="manual-entry">
      <div className="field-name">Type a value from the original</div>
      <div className="small muted">What you type is saved as confirmed by you and marked as typed by hand.</div>
      <div className="manual-entry-grid">
        <input
          className="input manual-name"
          placeholder={isRx ? "Medicine" : isText ? "Heading (Impression, Findings)" : "Test name"}
          aria-label={isRx ? "Medicine" : isText ? "Heading" : "Test name"}
          value={form.name}
          onChange={set("name")}
        />
        <input
          className={`input ${isText ? "manual-text" : "manual-value"}`}
          placeholder={isRx ? "Dose" : isText ? "Text" : "Result"}
          aria-label={isRx ? "Dose" : isText ? "Text" : "Result"}
          value={form.value}
          onChange={set("value")}
        />
        {!isText && !isRx ? (
          <input className="input manual-unit" placeholder="Unit" aria-label="Unit" value={form.unit} onChange={set("unit")} />
        ) : null}
        {!isText ? (
          <input
            className="input manual-range"
            placeholder={isRx ? "How often" : "Reference range"}
            aria-label={isRx ? "How often" : "Reference range"}
            value={form.reference_range}
            onChange={set("reference_range")}
          />
        ) : null}
        {!isText && !isRx ? (
          <input
            className="input manual-date"
            type="date"
            aria-label="Collected on"
            value={form.collected_at}
            onChange={set("collected_at")}
          />
        ) : null}
        <button
          className="btn btn-sm"
          onClick={() => add.mutate()}
          aria-busy={add.isPending || undefined}
          disabled={!allowed || add.isPending || !form.name.trim() || !form.value.trim()}
        >
          {add.isPending ? <><span className="spinner" /> Saving…</> : "Add value"}
        </button>
      </div>
      {!allowed ? <div className="small muted">Your role cannot enter values.</div> : null}
    </div>
  );
}

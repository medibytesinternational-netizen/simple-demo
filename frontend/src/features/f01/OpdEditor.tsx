import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { patch } from "../../api";
import type { Draft } from "../../types";
import { OPD_HEARD_SECTIONS } from "./opdFormat";

const textOf = (v: any): string => (v && typeof v === "object" ? String(v.text ?? "") : String(v ?? "")).trim();

/** A heading typed by the doctor: attributed to them, not to the recording. */
const authored = (text: string) => ({ text, source_event_ids: [], source_segment_ids: [], confidence: 1, human_authored: true });

/**
 * Edit an OPD report heading by heading. Unchanged headings keep their link to the recording;
 * changed ones are marked as written by the doctor. Saving rebuilds the note in the OPD format.
 */
export function OpdEditor({ draft, onDone, sections = OPD_HEARD_SECTIONS }: {
  draft: Draft;
  onDone: () => void;
  /** Headings to edit: the OPD format by default, or the admission format. */
  sections?: [string, string, boolean][];
}) {
  const queryClient = useQueryClient();
  const content = draft.content || {};
  const initial = Object.fromEntries(
    sections.map(([key, , many]) => [key, many ? (content[key] || []).map(textOf).filter(Boolean).join("\n") : textOf(content[key])]),
  ) as Record<string, string>;
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: () => {
      const next: Record<string, any> = { ...content };
      for (const [key, , many] of sections) {
        if (values[key] === initial[key]) continue; // untouched: keep the quote and its source
        if (many) {
          const old = (content[key] || []) as any[];
          next[key] = values[key].split("\n").map((t) => t.trim()).filter(Boolean)
            .map((t) => old.find((c) => textOf(c) === t) || authored(t));
        } else {
          next[key] = values[key].trim() ? authored(values[key].trim()) : null;
        }
      }
      next.not_documented = sections.filter(([key, , many]) => (many ? !(next[key] || []).length : !next[key])).map(([, label]) => label);
      return patch(`/drafts/${draft.id}`, { content: next });
    },
    onSuccess: () => {
      setError("");
      queryClient.invalidateQueries();
      onDone();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  return (
    <div className="opd-editor">
      {error ? <div className="error-box" role="alert">{error}</div> : null}
      {sections.map(([key, label, many]) => (
        <label key={key}>
          {label}
          {many ? <span className="hint">One per line</span> : null}
          <textarea
            className="textarea"
            rows={many || key === "history_of_present_illness" ? 3 : 1}
            value={values[key]}
            onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
          />
        </label>
      ))}
      <div className="button-row">
        <button className="btn" onClick={onDone} disabled={save.isPending}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={() => save.mutate()} disabled={save.isPending} aria-busy={save.isPending || undefined}>
          {save.isPending ? <><span className="spinner" /> Saving...</> : "Save changes"}
        </button>
        <span className="small muted">Changed headings are marked as written by you. Then sign to update the timeline.</span>
      </div>
    </div>
  );
}

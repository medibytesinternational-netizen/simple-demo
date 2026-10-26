import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../../api";
import { useCan } from "../../session";
import { READING_CATEGORIES, needsUnit, readingOk } from "./types";
import type { ReadingBody, ReadingCategory, ReadingResult } from "./types";
import { Panel } from "../../components/ui";

function nowLocal(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 16);
}

/** Record one ICU or ward reading with its unit, device and time. Mounted by the lead on the ICU tab. */
export default function IcuReadingForm({
  encounterId,
  onRecorded,
}: {
  encounterId?: string;
  onRecorded?: (result: ReadingResult) => void;
}) {
  const allowed = useCan("record_reading");
  const queryClient = useQueryClient();
  const [category, setCategory] = useState<ReadingCategory>("vitals");
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const [device, setDevice] = useState("");
  const [recordedAt, setRecordedAt] = useState(nowLocal());
  const [notice, setNotice] = useState("");

  const record = useMutation({
    mutationFn: (body: ReadingBody) => post<ReadingResult>("/icu/readings", body),
    onSuccess: (result) => {
      setNotice(
        result.duplicate ? "Already recorded: nothing was added." : `Recorded on the ${result.chart ?? ""} chart.`,
      );
      if (!result.duplicate) {
        setLabel("");
        setValue("");
        setUnit("");
      }
      queryClient.invalidateQueries({ queryKey: ["icu-flow-sheet"] });
      onRecorded?.(result);
    },
    onError: (error: Error) => setNotice(error.message),
  });

  if (!allowed) return null;

  const body: ReadingBody = {
    category,
    label,
    value,
    unit,
    device,
    recorded_at: recordedAt.length === 16 ? `${recordedAt}:00` : recordedAt,
    ...(encounterId ? { encounter_id: encounterId } : {}),
  };

  return (
    <Panel title="Record a reading" sub="Each value is saved with its unit, device and time. Nothing is estimated.">
      <div className="panel-body">
        <div className="icu-form">
          <label className="form-field">
            <span className="field-label">Type</span>
            <select className="select" value={category} onChange={(e) => setCategory(e.target.value as ReadingCategory)}>
              {READING_CATEGORIES.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>
          <label className="form-field">
            <span className="field-label">What was measured</span>
            <input className="input" value={label} placeholder="Heart rate" onChange={(e) => setLabel(e.target.value)} />
          </label>
          <label className="form-field">
            <span className="field-label">Value</span>
            <input className="input" value={value} onChange={(e) => setValue(e.target.value)} />
          </label>
          <label className="form-field">
            <span className="field-label">Unit{needsUnit(value) ? " (required)" : ""}</span>
            <input className="input" value={unit} placeholder="bpm" onChange={(e) => setUnit(e.target.value)} />
          </label>
          <label className="form-field">
            <span className="field-label">Device</span>
            <input className="input" value={device} placeholder="Bedside monitor" onChange={(e) => setDevice(e.target.value)} />
          </label>
          <label className="form-field">
            <span className="field-label">Time</span>
            <input className="input" type="datetime-local" value={recordedAt} onChange={(e) => setRecordedAt(e.target.value)} />
          </label>
        </div>
        <div className="button-row mt-3">
          <button
            className="btn btn-primary"
            disabled={!readingOk({ label, value, unit, recorded_at: recordedAt }) || record.isPending}
            aria-busy={record.isPending || undefined}
            onClick={() => record.mutate(body)}
          >
            {record.isPending ? <span className="spinner" /> : null}
            Record
          </button>
          {notice ? <span className="small muted" role="status">{notice}</span> : null}
        </div>
      </div>
    </Panel>
  );
}

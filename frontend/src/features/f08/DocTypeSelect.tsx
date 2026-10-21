import { DOC_TYPE_OPTIONS, type DocType } from "./types";

export function DocTypeSelect({ value, onChange }: { value: DocType; onChange: (value: DocType) => void }) {
  return (
    <label className="small muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
      Type
      <select
        className="select"
        style={{ width: 150, padding: "3px 6px", fontSize: 12 }}
        value={value}
        onChange={(event) => onChange(event.target.value as DocType)}
        aria-label="Document type"
      >
        {DOC_TYPE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}

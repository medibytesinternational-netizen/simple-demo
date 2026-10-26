import { DOC_TYPE_OPTIONS, type DocType } from "./types";

export function DocTypeSelect({ value, onChange }: { value: DocType; onChange: (value: DocType) => void }) {
  return (
    <label className="doc-type-select">
      <span className="doc-type-label">Type</span>
      <select
        className="select select-sm"
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

import type { ReactNode } from "react";
import { Icon } from "../icons";

/** Brisk-style row: search, filters and view controls on the left, count and actions on the right. */
export function Toolbar({ children, bare, label }: { children: ReactNode; bare?: boolean; label?: string }) {
  return <div className={`toolbar ${bare ? "bare" : ""}`} role="toolbar" aria-label={label}>{children}</div>;
}

export function SearchInput({ value, onChange, placeholder, label }: { value: string; onChange: (value: string) => void; placeholder: string; label?: string }) {
  return (
    <div className="toolbar-search" role="search">
      <Icon name="search" size={15} />
      <input className="input" type="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={label || placeholder} />
    </div>
  );
}

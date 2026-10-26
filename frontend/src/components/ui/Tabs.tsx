import { Fragment, useRef, type KeyboardEvent } from "react";

export type TabItem<K extends string> = { key: K; label: string; count?: number; countTone?: "critical" | "neutral"; group?: string };

/**
 * Tab strip with roving focus (arrow keys, Home, End). Selection is handed to
 * the caller's own handler so URL-driven pages keep their existing behaviour.
 */
export function Tabs<K extends string>({ items, value, onSelect, label, variant = "pill" }: {
  items: TabItem<NoInfer<K>>[];
  value: K;
  onSelect: (key: NoInfer<K>) => void;
  label: string;
  variant?: "pill" | "segmented";
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, index: number) => {
    const last = items.length - 1;
    const next = e.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : e.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : e.key === "Home" ? 0 : e.key === "End" ? last : -1;
    if (next < 0) return;
    e.preventDefault();
    refs.current[next]?.focus();
    onSelect(items[next].key);
  };
  return (
    <div className={variant === "segmented" ? "segmented" : "tabs"} role="tablist" aria-label={label}>
      {items.map((item, i) => {
        const selected = item.key === value;
        const newGroup = i > 0 && item.group && item.group !== items[i - 1].group;
        return (
          <Fragment key={item.key}>
            {newGroup ? <span className="tab-group-sep" aria-hidden="true" /> : null}
            <button
              ref={(el) => { refs.current[i] = el; }}
              type="button"
              role="tab"
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              className={variant === "segmented" ? (selected ? "active" : "") : `tab ${selected ? "active" : ""}`}
              onClick={() => onSelect(item.key)}
              onKeyDown={(e) => onKey(e, i)}
            >
              {item.label}
              {item.count ? <span className={variant === "segmented" ? "seg-count" : `tab-count ${item.countTone === "neutral" ? "neutral" : ""}`}>{item.count}</span> : null}
            </button>
          </Fragment>
        );
      })}
    </div>
  );
}

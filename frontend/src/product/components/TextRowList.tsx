import type { TextRow } from "../api/types";
import { formatPercent } from "../lib/format";
import { secondPassOf } from "../lib/rows";
import { StatusPill } from "./StatusPill";
import styles from "./TextRowList.module.css";

interface TextRowListProps {
  rows: readonly TextRow[];
  emptyText: string;
}

/** Vitals, symptoms and allergies: same row shape, same presentation. */
export function TextRowList({ rows, emptyText }: TextRowListProps) {
  if (rows.length === 0) return <p className={styles.empty}>{emptyText}</p>;
  return (
    <ul className={styles.list}>
      {rows.map((row, index) => (
        <li key={`${index}-${row.text}`} className={styles.row} data-color={row.color}>
          <StatusPill color={row.color} />
          <div className={styles.main}>
            <p className={styles.textLine}>
              <span className={`${styles.text} ${row.negated ? styles.negated : ""}`}>{row.text}</span>
              {row.negated && <span className={styles.tagNegated}>NEGATED</span>}
              {secondPassOf(row) && <span className={styles.tagInfo}>second pass</span>}
              <span className={styles.conf}>{formatPercent(row.confidence)}</span>
            </p>
            {row.note && <p className={styles.note}>{row.note}</p>}
            {row.source_sentence && (
              <details className={styles.heard}>
                <summary>Heard as</summary>
                <blockquote className={styles.quote}>{row.source_sentence}</blockquote>
              </details>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

import type { DischargeItem, DischargeSection } from "../api/types";
import { SECTION_TITLES, formatPercent } from "../lib/format";
import { Icon } from "./Icon";
import { VerifiedBadge } from "./VerifiedBadge";
import styles from "./NoteSection.module.css";

interface NoteSectionProps {
  section: DischargeSection;
  items: readonly DischargeItem[];
  /** The transcript talks about this section but nothing was written. */
  missing?: boolean;
}

export function NoteSection({ section, items, missing = false }: NoteSectionProps) {
  const headingId = `note-${section}`;
  const empty = items.length === 0;
  return (
    <section className={`${styles.card} ${empty ? styles.empty : ""}`} aria-labelledby={headingId} data-section={section}>
      <header className={styles.head}>
        <h3 id={headingId} className={styles.title}>
          {SECTION_TITLES[section]}
        </h3>
        {!empty && (
          <span className={styles.count}>
            {items.length} {items.length === 1 ? "item" : "items"}
          </span>
        )}
      </header>

      {empty && missing ? (
        <div className={`${styles.emptyState} ${styles.missing}`} role="status">
          <p className={styles.emptyTitle}>Spoken but not written</p>
          <p className={styles.emptyText}>
            The recording talks about this section, but no item passed the checks. Check the transcript.
          </p>
        </div>
      ) : empty ? (
        <div className={styles.emptyState}>
          <p className={styles.emptyTitle}>Nothing dictated</p>
          <p className={styles.emptyText}>No statement in the recording supports this section.</p>
        </div>
      ) : (
        <ul className={styles.items}>
          {items.map((item, index) => {
            const confidence = formatPercent(item.confidence);
            return (
              <li key={`${index}-${item.text}`} className={styles.item}>
                <p className={styles.text}>{item.text}</p>
                <div className={styles.meta}>
                  <VerifiedBadge status={item.verified_status} />
                  {confidence && <span className={styles.metaText}>{confidence} confidence</span>}
                  {item.verified_kind && <span className={styles.metaText}>{item.verified_kind}</span>}
                </div>
                {item.source_sentence && (
                  <details className={styles.heard}>
                    <summary>
                      <Icon name="chevron" size={14} className={styles.chevron} />
                      Heard as
                    </summary>
                    <blockquote className={styles.quote}>{item.source_sentence}</blockquote>
                  </details>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

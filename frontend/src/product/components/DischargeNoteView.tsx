import { DISCHARGE_SECTIONS, type DischargeNote } from "../api/types";
import { downloadJson } from "../lib/browser";
import { SECTION_TITLES } from "../lib/format";
import surface from "../styles/surface.module.css";
import { CopyButton } from "./CopyButton";
import { Icon } from "./Icon";
import { NoteSection } from "./NoteSection";
import styles from "./DischargeNoteView.module.css";

interface DischargeNoteViewProps {
  note: DischargeNote;
}

function countItems(note: DischargeNote): { total: number; verified: number } {
  let total = 0;
  let verified = 0;
  for (const key of DISCHARGE_SECTIONS) {
    const items = note.sections[key]?.items ?? [];
    total += items.length;
    verified += items.filter((i) => i.verified_status === "verified").length;
  }
  return { total, verified };
}

export function DischargeNoteView({ note }: DischargeNoteViewProps) {
  const { provenance } = note;
  const { total, verified } = countItems(note);
  const schemaValid = provenance.schema !== "INVALID";
  const schemaTone = provenance.schema === "valid" ? styles.good : provenance.schema === "INVALID" ? styles.bad : "";
  const missing = provenance.coverage?.missing;
  const unused = DISCHARGE_SECTIONS.flatMap((k) =>
    (provenance.coverage?.unused?.[k] ?? []).map((quote) => ({ section: k, quote })),
  );

  return (
    <div className={styles.view}>
      <header className={styles.header}>
        <div className={styles.headText}>
          <h2 className={styles.title}>Discharge note</h2>
          <p className={styles.summary}>
            {total === 0
              ? "No items were written."
              : `${total} ${total === 1 ? "item" : "items"}, ${verified} verified against the transcript.`}
          </p>
        </div>
        <div className={styles.actions}>
          <CopyButton getText={() => JSON.stringify(note, null, 2)} />
          <button
            type="button"
            className={surface.button}
            onClick={() => downloadJson("discharge.json", note)}
          >
            <Icon name="download" />
            Download discharge.json
          </button>
        </div>
        <dl className={styles.provenance} aria-label="Provenance">
          <div className={`${styles.prov} ${schemaTone}`}>
            <dt>Schema</dt>
            <dd>
              {provenance.schema && <Icon name={schemaValid ? "check" : "cross"} size={12} />}
              {provenance.schema ?? "not checked"}
            </dd>
          </div>
          {provenance.dropped_unproven !== undefined && (
            <div className={`${styles.prov} ${provenance.dropped_unproven > 0 ? styles.warn : ""}`}>
              <dt>Dropped unproven</dt>
              <dd>{provenance.dropped_unproven}</dd>
            </div>
          )}
          {missing && (
            <div className={`${styles.prov} ${missing.length > 0 ? styles.warn : ""}`}>
              <dt>Missing sections</dt>
              <dd>{missing.length === 0 ? "none" : missing.map((k) => SECTION_TITLES[k]).join(", ")}</dd>
            </div>
          )}
          {provenance.prefilled !== undefined && (
            <div className={styles.prov}>
              <dt>Prefilled</dt>
              <dd>{provenance.prefilled}</dd>
            </div>
          )}
          {provenance.llm_engine && (
            <div className={styles.prov}>
              <dt>Engine</dt>
              <dd className={styles.mono}>{provenance.llm_engine}</dd>
            </div>
          )}
        </dl>
        {unused.length > 0 && (
          <details className={styles.unused}>
            <summary>
              {unused.length} dictated {unused.length === 1 ? "part" : "parts"} not written in the note
            </summary>
            <ul>
              {unused.map(({ section, quote }) => (
                <li key={`${section}-${quote}`}>
                  <strong>{SECTION_TITLES[section]}:</strong> “{quote}”
                </li>
              ))}
            </ul>
          </details>
        )}
        {!schemaValid && provenance.schema_error && (
          <p className={styles.schemaError} role="alert">
            Schema check failed: {provenance.schema_error}
          </p>
        )}
      </header>

      <div className={styles.grid}>
        {DISCHARGE_SECTIONS.map((key) => (
          <NoteSection
            key={key}
            section={key}
            items={note.sections[key]?.items ?? []}
            missing={missing?.includes(key) ?? false}
          />
        ))}
      </div>
    </div>
  );
}

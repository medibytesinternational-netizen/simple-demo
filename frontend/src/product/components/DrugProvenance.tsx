import type { Candidate, DrugRow, ReferenceBlock, Validation } from "../api/types";
import { formatPercent } from "../lib/format";
import styles from "./DrugProvenance.module.css";

const VERDICT_LABELS: Record<Validation["status"], string> = {
  corrected: "Corrected",
  ambiguous: "Ambiguous, sent for human review",
  rejected: "Rejected, no candidate fits",
  skipped: "Skipped, matcher answer stands",
};

const VERDICT_TONE: Record<Validation["status"], string | undefined> = {
  corrected: styles.toneGood,
  ambiguous: styles.toneBad,
  rejected: styles.toneBad,
  skipped: styles.toneNeutral,
};

function CandidateList({ candidates, chosen }: { candidates: readonly Candidate[]; chosen: string }) {
  return (
    <ol className={styles.candidates}>
      {candidates.map((c) => {
        const isChosen = c.name.toLowerCase() === chosen.toLowerCase();
        const pct = Math.max(0, Math.min(1, c.score));
        return (
          <li key={`${c.name}-${c.score}`} className={`${styles.candidate} ${isChosen ? styles.chosen : ""}`}>
            <div className={styles.candHead}>
              <span className={styles.candName}>
                {c.name}
                {isChosen && <span className={styles.tagChosen}>chosen</span>}
                {c.dose_implausible && <span className={styles.tagWarn}>dose implausible</span>}
              </span>
              <span className={styles.score}>{c.score.toFixed(3)}</span>
            </div>
            <span className={styles.track} aria-hidden="true">
              <span className={styles.barFill} style={{ transform: `scaleX(${pct})` }} />
            </span>
            {(c.matched_alias || c.source) && (
              <span className={styles.candMeta}>
                {c.matched_alias && c.matched_alias !== c.name && <>alias {c.matched_alias}</>}
                {c.matched_alias && c.matched_alias !== c.name && c.source && " · "}
                {c.source && <>{c.source === "mini" ? "curated list" : "India reference"}</>}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function ReferenceLine({ reference }: { reference: ReferenceBlock }) {
  const parts = [
    reference.kind === "brand" ? `brand ${reference.name}` : reference.name,
    reference.substances.length > 0 && reference.substances.join(" + ") !== reference.name
      ? reference.substances.join(" + ")
      : null,
    reference.units.length > 0 ? `units ${reference.units.join("/")}` : null,
    reference.mass_mg ? `${reference.mass_mg[0]} to ${reference.mass_mg[1]} mg per unit` : null,
  ].filter((p): p is string => Boolean(p));
  return <>{parts.join(", ")}</>;
}

interface DrugProvenanceProps {
  row: DrugRow;
  id: string;
}

/** How a drug row came to be: what was heard, what the matcher and gpt-4.1 decided, and why. */
export function DrugProvenance({ row, id }: DrugProvenanceProps) {
  const { validation, context_repair: repair } = row;
  const heard = row.raw_token ?? repair?.heard;
  const reference = row.reference ?? row.candidates?.find((c) => c.name === row.name)?.reference;
  const verdictConfidence = formatPercent(validation?.semantic_confidence_score);

  return (
    <div className={styles.panel} id={id}>
      {heard && (
        <p className={styles.heardLine}>
          <span className={styles.heardLabel}>Heard</span>
          <q className={styles.heard}>{heard}</q>
          <span aria-hidden="true" className={styles.arrow}>
            →
          </span>
          <span className="visually-hidden">became</span>
          <strong className={styles.chosenName}>{row.name}</strong>
        </p>
      )}

      <dl className={styles.facts}>
        {row.matcher_pick && (
          <div>
            <dt>Matcher pick</dt>
            <dd>
              {row.matcher_pick}
              {validation?.overrules_matcher && <span className={styles.tagWarn}>overruled by gpt-4.1</span>}
            </dd>
          </div>
        )}

        {row.candidates && row.candidates.length > 0 && (
          <div className={styles.wide}>
            <dt>Shortlist shown to gpt-4.1</dt>
            <dd>
              <CandidateList candidates={row.candidates} chosen={row.name} />
            </dd>
          </div>
        )}

        {validation && (
          <div className={styles.wide}>
            <dt>gpt-4.1 verdict</dt>
            <dd className={styles.verdict}>
              <span className={`${styles.verdictStatus} ${VERDICT_TONE[validation.status] ?? ""}`}>
                {VERDICT_LABELS[validation.status] ?? validation.status}
              </span>
              {verdictConfidence && <span className={styles.subtle}>{verdictConfidence} confidence</span>}
              {validation.engine && <span className={styles.mono}>{validation.engine}</span>}
              {validation.reason && <p className={styles.reason}>{validation.reason}</p>}
              {validation.applied_corrections && validation.applied_corrections.length > 0 && (
                <ul className={styles.corrections}>
                  {validation.applied_corrections.map((c) => (
                    <li key={`${c.replaced_token}-${c.substituted_with}`}>
                      <q>{c.replaced_token}</q> replaced with <strong>{c.substituted_with}</strong>
                    </li>
                  ))}
                </ul>
              )}
              {validation.unit_filtered && validation.unit_filtered.length > 0 && (
                <p className={styles.subtle}>Filtered out by unit: {validation.unit_filtered.join(", ")}</p>
              )}
            </dd>
          </div>
        )}

        {repair && (
          <div className={styles.wide}>
            <dt>Added by context repair</dt>
            <dd>
              <span className={styles.mono}>{repair.model}</span> recovered <q>{repair.heard}</q> from the sentence
              {repair.shortlist.length > 0 && (
                <> (shortlist {repair.shortlist.map(([name, score]) => `${name} ${score.toFixed(2)}`).join(", ")})</>
              )}
              .
            </dd>
          </div>
        )}

        {row.second_pass && (
          <div>
            <dt>Second pass</dt>
            <dd>Heard only by {row.second_pass}, not by MedASR</dd>
          </div>
        )}

        {reference && (
          <div>
            <dt>Reference</dt>
            <dd>
              <ReferenceLine reference={reference} />
            </dd>
          </div>
        )}

        {row.note && (
          <div className={styles.wide}>
            <dt>Note</dt>
            <dd>{row.note}</dd>
          </div>
        )}

        {row.source_sentence && (
          <div className={styles.wide}>
            <dt>Source sentence</dt>
            <dd>
              <blockquote className={styles.quote}>{row.source_sentence}</blockquote>
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

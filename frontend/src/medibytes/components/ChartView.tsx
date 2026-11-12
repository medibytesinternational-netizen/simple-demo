import { useState } from "react";
import type { Entities, TextRow } from "../api/types";
import { DrugRowItem } from "./DrugRowItem";
import { StatusPill } from "./StatusPill";
import { tabId, tabPanelId } from "../lib/tabs";
import { Tabs, type TabSpec } from "./Tabs";
import { TextRowList } from "./TextRowList";
import styles from "./ChartView.module.css";

type ChartTab = "drugs" | "vitals" | "allergies" | "symptoms";

const PREFIX = "chart";

interface ChartViewProps {
  entities: Entities;
}

function hasText(row: Partial<TextRow>): row is Partial<TextRow> & { text: string } {
  return typeof row.text === "string" && row.text.trim().length > 0;
}

function ClinicalLine({ label, row }: { label: string; row: Partial<TextRow> & { text: string } }) {
  return (
    <div className={styles.clinical}>
      <dt>{label}</dt>
      <dd>
        {row.color && <StatusPill color={row.color} compact />}
        <span>{row.text}</span>
      </dd>
    </div>
  );
}

export function ChartView({ entities }: ChartViewProps) {
  const [tab, setTab] = useState<ChartTab>("drugs");
  const { drugs, vitals, allergies, symptoms, diagnosis, followup, context_repair: repair } = entities;

  const tabs: TabSpec<ChartTab>[] = [
    { id: "drugs", label: "Drugs", count: drugs.length },
    { id: "vitals", label: "Vitals", count: vitals.length },
    { id: "allergies", label: "Allergies", count: allergies.length },
    { id: "symptoms", label: "Symptoms", count: symptoms.length },
  ];

  const showClinical = hasText(diagnosis) || hasText(followup);

  return (
    <section className={styles.card} aria-labelledby="chart-title">
      <header className={styles.head}>
        <h2 id="chart-title" className={styles.title}>
          Extracted chart
        </h2>
        <p className={styles.sub}>Every row links back to what was heard. Select a drug to see how it was chosen.</p>
      </header>

      {showClinical && (
        <dl className={styles.clinicalList}>
          {hasText(diagnosis) && <ClinicalLine label="Diagnosis" row={diagnosis} />}
          {hasText(followup) && <ClinicalLine label="Follow-up" row={followup} />}
        </dl>
      )}

      <Tabs tabs={tabs} active={tab} onChange={(id) => setTab(id as ChartTab)} idPrefix={PREFIX} label="Chart categories" variant="secondary" />

      <div
        role="tabpanel"
        id={tabPanelId(PREFIX, tab)}
        aria-labelledby={tabId(PREFIX, tab)}
        className={styles.panel}
        tabIndex={0}
      >
        {tab === "drugs" &&
          (drugs.length === 0 ? (
            <p className={styles.empty}>No drugs dictated.</p>
          ) : (
            <ul className={styles.drugs}>
              {drugs.map((row, index) => (
                <DrugRowItem key={`${index}-${row.name}`} row={row} />
              ))}
            </ul>
          ))}
        {tab === "vitals" && <TextRowList rows={vitals} emptyText="No vitals dictated." />}
        {tab === "allergies" && <TextRowList rows={allergies} emptyText="No allergies dictated." />}
        {tab === "symptoms" && <TextRowList rows={symptoms} emptyText="No symptoms dictated." />}
      </div>

      {(entities.term_validator || repair) && (
        <p className={styles.footer}>
          {entities.term_validator && <>Term validation: {entities.term_validator}. </>}
          {repair &&
            (repair.status === "ran"
              ? `Context repair considered ${repair.considered ?? 0}, repaired ${repair.repaired?.length ?? 0}, declined ${repair.declined?.length ?? 0}.`
              : `Context repair skipped${repair.reason ? `: ${repair.reason}` : ""}.`)}
        </p>
      )}
    </section>
  );
}

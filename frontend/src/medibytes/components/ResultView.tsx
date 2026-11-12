import { useState } from "react";
import type { JobResult } from "../api/types";
import { formatClock } from "../lib/format";
import { isAudioArtefact } from "../lib/files";
import { tabId, tabPanelId } from "../lib/tabs";
import { JsonView } from "./JsonView";
import { Tabs, type TabSpec } from "./Tabs";
import { TranscriptView } from "./TranscriptView";
import styles from "./ResultView.module.css";

export type ResultTab = "transcript" | "json";

const PREFIX = "result";

const TABS: readonly TabSpec<ResultTab>[] = [
  { id: "transcript", label: "Transcript" },
  { id: "json", label: "JSON" },
];

interface ResultViewProps {
  result: JobResult;
  filename: string;
  /** Resolves an artefact name from `result.files` to a URL. */
  fileUrl: (name: string) => string;
  initialTab?: ResultTab;
}

export function ResultView({ result, filename, fileUrl, initialTab = "transcript" }: ResultViewProps) {
  const [tab, setTab] = useState<ResultTab>(initialTab);
  const otherFiles = result.files.filter((f) => !isAudioArtefact(f));

  return (
    <section className={styles.result} aria-label="Result">
      <div className={styles.bar}>
        <p className={styles.caption}>
          <span className={styles.file}>{filename}</span>
          <span>{formatClock(result.audio.duration_s)} audio</span>
        </p>
        <Tabs tabs={TABS} active={tab} onChange={(id) => setTab(id as ResultTab)} idPrefix={PREFIX} label="Result views" />
      </div>

      <div role="tabpanel" id={tabPanelId(PREFIX, tab)} aria-labelledby={tabId(PREFIX, tab)} className={styles.panel}>
        {tab === "transcript" && <TranscriptView transcript={result.transcript} entities={result.entities} />}
        {tab === "json" && (
          <>
            <JsonView data={result.discharge} filename="discharge.json" />
            {otherFiles.length > 0 && (
              <nav className={styles.files} aria-label="Other pipeline artefacts">
                <span className={styles.filesLabel}>Other artefacts</span>
                {otherFiles.map((f) => (
                  <a key={f} href={fileUrl(f)} target="_blank" rel="noreferrer">
                    {f}
                  </a>
                ))}
              </nav>
            )}
          </>
        )}
      </div>
    </section>
  );
}

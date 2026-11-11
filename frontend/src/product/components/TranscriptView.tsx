import { useMemo, useState } from "react";
import type { Color, Entities, Transcript } from "../api/types";
import { COLOR_MEANINGS } from "../lib/format";
import { collectSpans, splitBySpans } from "../lib/highlight";
import styles from "./TranscriptView.module.css";

type Mode = "highlighted" | "raw";

interface TranscriptViewProps {
  transcript: Transcript;
  entities: Entities;
}

const MARK_CLASS: Record<Color, string | undefined> = {
  GREEN: styles.markGreen,
  YELLOW: styles.markYellow,
  RED: styles.markRed,
};

const COLORS: readonly Color[] = ["GREEN", "YELLOW", "RED"];

export function TranscriptView({ transcript, entities }: TranscriptViewProps) {
  const [mode, setMode] = useState<Mode>("highlighted");
  const spans = useMemo(() => collectSpans(entities), [entities]);
  const pieces = useMemo(() => splitBySpans(transcript.normalized_en, spans), [transcript.normalized_en, spans]);
  const highlighted = pieces.filter((p) => p.span !== null).length;

  return (
    <section className={styles.card} aria-labelledby="transcript-title">
      <header className={styles.head}>
        <div>
          <h2 id="transcript-title" className={styles.title}>
            Transcript
          </h2>
          <p className={styles.meta}>
            <span className={styles.mono}>{transcript.stt_engine}</span>
            <span>{transcript.language}</span>
            {mode === "highlighted" && <span>{highlighted} exact entity spans</span>}
          </p>
        </div>
        <div className={styles.toggle} role="group" aria-label="Transcript version">
          <button type="button" aria-pressed={mode === "highlighted"} onClick={() => setMode("highlighted")}>
            Normalised
          </button>
          <button type="button" aria-pressed={mode === "raw"} onClick={() => setMode("raw")}>
            Raw ASR
          </button>
        </div>
      </header>

      {mode === "highlighted" ? (
        <>
          <ul className={styles.legend} aria-label="Highlight legend">
            {COLORS.map((c) => (
              <li key={c}>
                <span className={`${styles.swatch} ${MARK_CLASS[c] ?? ""}`} aria-hidden="true" />
                {c}: {COLOR_MEANINGS[c]}
              </li>
            ))}
          </ul>
          <p className={styles.text} data-testid="transcript-text">
            {pieces.map((piece, index) =>
              piece.span ? (
                <mark
                  key={index}
                  className={`${styles.mark} ${MARK_CLASS[piece.span.color] ?? ""}`}
                  title={`${piece.span.kind}: ${piece.span.label} (${piece.span.color})`}
                  data-color={piece.span.color}
                  data-kind={piece.span.kind}
                >
                  {piece.text}
                </mark>
              ) : (
                <span key={index}>{piece.text}</span>
              ),
            )}
          </p>
          <p className={styles.footnote}>
            Only entities whose position in the transcript is exact are highlighted.
          </p>
        </>
      ) : (
        <p className={styles.text} data-testid="transcript-text">
          {transcript.text}
        </p>
      )}
    </section>
  );
}

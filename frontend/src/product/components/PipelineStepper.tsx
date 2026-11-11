import type { JobStatus, StageName, StageState, StageStatus } from "../api/types";
import {
  JOB_STATUS_LABELS,
  STAGE_HINTS,
  STAGE_LABELS,
  STAGE_ORDER,
  STAGE_STATE_LABELS,
  formatSeconds,
} from "../lib/format";
import { Icon, type IconName } from "./Icon";
import styles from "./PipelineStepper.module.css";

interface PipelineStepperProps {
  /** Live stages from the job; omitted before any job exists (all shown pending). */
  stages: readonly StageStatus[] | null;
  status: JobStatus | null;
  filename: string | null;
  error: string | null;
  reconnecting: boolean;
}

const STATE_ICON: Record<StageState, IconName> = {
  pending: "circle",
  running: "spinner",
  done: "check",
  degraded: "warning",
  failed: "cross",
};

const STATE_CLASS: Record<StageState, string | undefined> = {
  pending: styles.pending,
  running: styles.running,
  done: styles.done,
  degraded: styles.degraded,
  failed: styles.failed,
};

/** Always render the seven stages in pipeline order, even if the server omits some. */
function normalise(stages: readonly StageStatus[] | null): StageStatus[] {
  const byName = new Map<StageName, StageStatus>((stages ?? []).map((s) => [s.name, s]));
  return STAGE_ORDER.map(
    (name) =>
      byName.get(name) ?? { name, label: STAGE_LABELS[name], state: "pending", seconds: null, detail: "" },
  );
}

function announcement(list: StageStatus[], status: JobStatus | null): string {
  if (!status) return "";
  if (status === "succeeded") return "Pipeline finished. Discharge note ready.";
  if (status === "failed") {
    const failed = list.find((s) => s.state === "failed");
    return failed ? `Pipeline failed at ${failed.label}.` : "Pipeline failed.";
  }
  const running = list.find((s) => s.state === "running");
  if (running) return `${running.label} running.`;
  return status === "queued" ? "Queued." : "";
}

export function PipelineStepper({ stages, status, filename, error, reconnecting }: PipelineStepperProps) {
  const list = normalise(stages);
  const finished = list.filter((s) => s.state === "done" || s.state === "degraded").length;
  const total = list.length;
  const totalSeconds = list.reduce((sum, s) => sum + (s.seconds ?? 0), 0);

  return (
    <section className={styles.panel} aria-labelledby="pipeline-title">
      <div className={styles.head}>
        <div className={styles.headText}>
          <h2 id="pipeline-title" className={styles.title}>
            Pipeline
          </h2>
          <p className={styles.sub}>
            {filename ? (
              <>
                <span className={styles.file}>{filename}</span>
                {status && <span className={styles.status}>{JOB_STATUS_LABELS[status]}</span>}
                {status === "succeeded" && totalSeconds > 0 && <span>{formatSeconds(totalSeconds)} total</span>}
              </>
            ) : (
              "Upload a dictation to start. Each stage reports here as it runs."
            )}
          </p>
        </div>
        <span className={styles.counter} aria-hidden="true">
          {finished}/{total}
        </span>
      </div>

      <div
        className={styles.bar}
        role="progressbar"
        aria-label="Pipeline progress"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={finished}
        aria-valuetext={`${finished} of ${total} stages complete`}
      >
        <span className={styles.fill} style={{ transform: `scaleX(${finished / total})` }} />
      </div>

      <p className="visually-hidden" aria-live="polite" aria-atomic="true">
        {announcement(list, status)}
      </p>

      {reconnecting && (
        <p className={styles.notice} role="status">
          <Icon name="refresh" size={14} />
          Connection lost. Retrying.
        </p>
      )}

      <ol className={styles.steps}>
        {list.map((stage, index) => {
          const seconds = formatSeconds(stage.seconds);
          const detail = stage.detail || (stage.state === "pending" ? STAGE_HINTS[stage.name] : "");
          return (
            <li
              key={stage.name}
              className={`${styles.step} ${STATE_CLASS[stage.state] ?? ""}`}
              aria-current={stage.state === "running" ? "step" : undefined}
              data-state={stage.state}
            >
              <span className={styles.marker}>
                <Icon name={STATE_ICON[stage.state]} size={14} className={stage.state === "running" ? styles.spin : undefined} />
              </span>
              <div className={styles.body}>
                <p className={styles.labelRow}>
                  <span className={styles.label}>
                    <span className={styles.index} aria-hidden="true">
                      {index + 1}
                    </span>
                    {stage.label || STAGE_LABELS[stage.name]}
                  </span>
                  <span className={styles.state}>{STAGE_STATE_LABELS[stage.state]}</span>
                  {seconds && <span className={styles.seconds}>{seconds}</span>}
                </p>
                {detail && <p className={styles.detail}>{detail}</p>}
              </div>
            </li>
          );
        })}
      </ol>

      {error && (
        <p className={styles.error} role="alert">
          <Icon name="cross" size={16} />
          {error}
        </p>
      )}
    </section>
  );
}

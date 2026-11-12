import type { JobStatus, JobSummary } from "../api/types";
import { JOB_STATUS_LABELS, formatDateTime } from "../lib/format";
import { Icon, type IconName } from "./Icon";
import styles from "./RecentJobs.module.css";

interface RecentJobsProps {
  jobs: readonly JobSummary[];
  activeJobId: string | null;
  loading: boolean;
  error: string | null;
  onOpen: (jobId: string) => void;
  onRefresh: () => void;
  limit?: number;
}

const STATUS_ICON: Record<JobStatus, IconName> = {
  queued: "circle",
  running: "spinner",
  succeeded: "check",
  failed: "cross",
};

const STATUS_CLASS: Record<JobStatus, string | undefined> = {
  queued: styles.queued,
  running: styles.running,
  succeeded: styles.succeeded,
  failed: styles.failed,
};

export function RecentJobs({ jobs, activeJobId, loading, error, onOpen, onRefresh, limit = 8 }: RecentJobsProps) {
  const shown = jobs.slice(0, limit);
  return (
    <section className={styles.card} aria-labelledby="recent-title">
      <header className={styles.head}>
        <h2 id="recent-title" className={styles.title}>
          Recent jobs
        </h2>
        <button type="button" className={styles.refresh} onClick={onRefresh} aria-label="Refresh recent jobs">
          <Icon name="refresh" size={16} />
        </button>
      </header>

      {error ? (
        <p className={styles.message} role="status">
          {error}
        </p>
      ) : loading && jobs.length === 0 ? (
        <p className={styles.message}>Loading</p>
      ) : shown.length === 0 ? (
        <p className={styles.message}>Processed dictations will be listed here.</p>
      ) : (
        <ul className={styles.list}>
          {shown.map((job) => {
            const active = job.job_id === activeJobId;
            return (
              <li key={job.job_id}>
                <button
                  type="button"
                  className={`${styles.item} ${active ? styles.active : ""}`}
                  onClick={() => onOpen(job.job_id)}
                  aria-current={active ? "true" : undefined}
                >
                  <span className={`${styles.status} ${STATUS_CLASS[job.status] ?? ""}`}>
                    <Icon name={STATUS_ICON[job.status]} size={13} />
                    <span className="visually-hidden">{JOB_STATUS_LABELS[job.status]}</span>
                  </span>
                  <span className={styles.name}>{job.filename}</span>
                  <time className={styles.time} dateTime={job.created_at}>
                    {formatDateTime(job.created_at)}
                  </time>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

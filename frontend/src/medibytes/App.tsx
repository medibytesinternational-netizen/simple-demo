import { useCallback } from "react";
import { apiClient, type ApiClient } from "./api/client";
import { AudioPlayer } from "./components/AudioPlayer";
import { ChartView } from "./components/ChartView";
import { DischargeNoteView } from "./components/DischargeNoteView";
import { Header } from "./components/Header";
import { JsonView } from "./components/JsonView";
import { PipelineStepper } from "./components/PipelineStepper";
import { RecentJobs } from "./components/RecentJobs";
import { ResultView } from "./components/ResultView";
import { UploadPanel } from "./components/UploadPanel";
import { useHealth } from "./hooks/useHealth";
import { isTerminal, useJob } from "./hooks/useJob";
import { useRecentJobs } from "./hooks/useRecentJobs";
import { audioSources } from "./lib/files";
import styles from "./App.module.css";

interface AppProps {
  client?: ApiClient;
}

/** Composition root: wires hooks (the only API consumers) to presentational components. */
export function App({ client = apiClient }: AppProps) {
  const job = useJob(client);
  const health = useHealth(client);

  const current = job.job;
  const running = current !== null && !isTerminal(current.status);
  const waitingFirstPoll = job.jobId !== null && current === null && job.pollError === null;
  const busy = job.uploading || running || waitingFirstPoll;
  const result = current?.status === "succeeded" ? current.result : null;
  const fileUrl = useCallback((name: string) => client.fileUrl(job.jobId ?? "", name), [client, job.jobId]);
  const recent = useRecentJobs(client, `${job.jobId ?? ""}:${current?.status ?? ""}`);
  const pipelineError = job.submitError || job.pollError || current?.error || null;

  return (
    <div className={styles.app}>
      <Header />
      <main className={styles.main}>
        <p className={styles.health} role="status">
          {health.loading
            ? "Checking the MediBytes API…"
            : health.health?.llm.configured
              ? `${health.health.llm.model} is configured · ${health.health.pipeline}`
              : health.error || "OPENAI_API_KEY is not configured; uploads are unavailable."}
        </p>

        <div className={styles.layout}>
          <aside className={styles.sidebar} aria-label="Dictation processing">
            <UploadPanel
              onSubmit={(file) => void job.submit(file)}
              busy={busy}
              uploading={job.uploading}
              serverError={job.submitError}
            />
            <PipelineStepper
              stages={current?.stages ?? null}
              status={current?.status ?? null}
              filename={current?.filename ?? null}
              error={pipelineError}
              reconnecting={job.reconnecting}
            />
            <RecentJobs
              jobs={recent.jobs}
              activeJobId={job.jobId}
              loading={recent.loading}
              error={recent.error}
              onOpen={job.open}
              onRefresh={recent.refresh}
            />
          </aside>

          <section className={styles.outputs} aria-label="Pipeline output">
            {current && result ? (
              <>
                <AudioPlayer sources={audioSources(result.files, fileUrl)} audio={result.audio} />
                <ResultView result={result} filename={current.filename} fileUrl={fileUrl} />
                <ChartView entities={result.entities} />
                <JsonView data={result.verify} filename="verify.json" title="Verification results" />
                <DischargeNoteView note={result.discharge} />
              </>
            ) : current?.status === "succeeded" ? (
              <p className={styles.notice} role="alert">
                The job finished but the server returned no result.
              </p>
            ) : (
              <p className={styles.empty}>
                Upload a recording or choose a recent job to review its transcript, extracted chart, verification and
                six-section discharge note.
              </p>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

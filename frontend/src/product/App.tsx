import { useCallback } from "react";
import { apiClient, type ApiClient } from "./api/client";
import { Header } from "./components/Header";
import { ResultView } from "./components/ResultView";
import { UploadPanel } from "./components/UploadPanel";
import { isTerminal, useJob } from "./hooks/useJob";
import styles from "./App.module.css";

interface AppProps {
  client?: ApiClient;
}

/** Composition root: wires hooks (the only API consumers) to presentational components. */
export function App({ client = apiClient }: AppProps) {
  const job = useJob(client);

  const current = job.job;
  const running = current !== null && !isTerminal(current.status);
  const waitingFirstPoll = job.jobId !== null && current === null && job.pollError === null;
  const busy = job.uploading || running || waitingFirstPoll;
  const result = current?.status === "succeeded" ? current.result : null;
  const fileUrl = useCallback((name: string) => client.fileUrl(job.jobId ?? "", name), [client, job.jobId]);

  return (
    <div className={styles.app}>
      <Header />
      <main className={styles.main}>
        <p className={styles.notice} role="status">
          Frontend-only preview. Audio processing requires an API service, which is not included here.
        </p>
        <div className={styles.upload}>
          <UploadPanel
            onSubmit={(file) => void job.submit(file)}
            busy={busy}
            uploading={job.uploading}
            serverError={job.submitError}
          />
        </div>

        {current && result && (
          <ResultView key={current.job_id} result={result} filename={current.filename} fileUrl={fileUrl} />
        )}
        {current?.status === "succeeded" && !result && (
          <p className={styles.notice} role="alert">
            The job finished but the server returned no result.
          </p>
        )}
      </main>
    </div>
  );
}

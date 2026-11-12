import { useId, useRef, useState, type ChangeEvent, type DragEvent, type FormEvent } from "react";
import { formatBytes } from "../lib/format";
import { ACCEPT_ATTRIBUTE, ACCEPTED_EXTENSIONS, validateUpload } from "../lib/upload";
import surface from "../styles/surface.module.css";
import { Icon } from "./Icon";
import styles from "./UploadPanel.module.css";

interface UploadPanelProps {
  onSubmit: (file: File) => void;
  /** Upload in flight or a job is still processing. */
  busy: boolean;
  uploading: boolean;
  /** Error `detail` returned by the server for the last upload. */
  serverError: string | null;
}

export function UploadPanel({ onSubmit, busy, uploading, serverError }: UploadPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  // A server error stays in the parent until the next upload; hide it once the user picks a new file.
  const [dismissedServerError, setDismissedServerError] = useState<string | null>(null);
  const dragDepth = useRef(0);
  const ids = useId();
  const hintId = `${ids}-hint`;
  const errorId = `${ids}-error`;

  const choose = (candidate: File | undefined) => {
    if (!candidate) return;
    const reason = validateUpload(candidate);
    setClientError(reason);
    setDismissedServerError(serverError);
    setFile(reason ? null : candidate);
  };

  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    choose(event.target.files?.[0]);
    // Allow choosing the same file again after an error.
    event.target.value = "";
  };

  const onDragEnter = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepth.current += 1;
    setDragging(true);
  };

  const onDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    if (busy) return;
    choose(event.dataTransfer.files[0]);
  };

  const onFormSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!file || busy) return;
    setDismissedServerError(null);
    onSubmit(file);
  };

  const error = clientError ?? (serverError !== dismissedServerError ? serverError : null);

  return (
    <section className={styles.panel} aria-labelledby={`${ids}-title`}>
      <h2 id={`${ids}-title`} className={styles.title}>
        New dictation
      </h2>
      <form onSubmit={onFormSubmit} noValidate>
        <div
          className={`${styles.drop} ${dragging ? styles.dragging : ""} ${error ? styles.invalid : ""}`}
          onDragEnter={onDragEnter}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          data-testid="dropzone"
        >
          <span className={styles.dropIcon}>
            <Icon name={file ? "file" : "upload"} size={24} />
          </span>
          {file ? (
            <p className={styles.fileName}>
              <span className={styles.name}>{file.name}</span>
              <span className={styles.size}>{formatBytes(file.size)}</span>
            </p>
          ) : (
            <p className={styles.prompt}>Drop an audio file here</p>
          )}
          <p id={hintId} className={styles.hint}>
            {ACCEPTED_EXTENSIONS.join(" ")}, up to 64 MB
          </p>
          <label className={surface.button}>
            <input
              type="file"
              accept={ACCEPT_ATTRIBUTE}
              className="visually-hidden"
              onChange={onInputChange}
              disabled={busy}
              aria-describedby={error ? `${hintId} ${errorId}` : hintId}
              aria-invalid={error ? true : undefined}
            />
            {file ? "Choose another file" : "Browse files"}
          </label>
        </div>

        {error && (
          <p id={errorId} className={styles.error} role="alert">
            <Icon name="warning" size={16} />
            {error}
          </p>
        )}

        <button type="submit" className={`${surface.primary} ${styles.submit}`} disabled={!file || busy}>
          {uploading ? (
            <>
              <Icon name="spinner" className={styles.spin} />
              Uploading
            </>
          ) : busy ? (
            <>
              <Icon name="spinner" className={styles.spin} />
              Processing
            </>
          ) : (
            "Process dictation"
          )}
        </button>
      </form>
    </section>
  );
}

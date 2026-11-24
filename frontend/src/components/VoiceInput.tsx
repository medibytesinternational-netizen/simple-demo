import { useEffect, useRef, useState } from "react";
import { ApiError, getTranscription, transcribeAudio, type MediBytesNote, type TranscriptionJob } from "../api";

const MAX_AUDIO_BYTES = 64 * 1024 * 1024;
const AUDIO_EXTENSIONS = ["mp3", "wav", "m4a", "mp4", "aac", "flac", "ogg", "webm"];
export const CONSENT_MESSAGE = "Record patient consent before capturing audio.";
const POLL_INTERVAL_MS = 5000;
const MAX_POLL_ATTEMPTS = 180;

export type VoiceSource = "record" | "upload";

type RetryUpload = { blob: Blob; filename: string; source: VoiceSource; audioId: string };
type Props = {
  consentGranted: boolean;
  encounterId: string;
  disabled?: boolean;
  onTranscript: (text: string, source: VoiceSource, transcriptEventId: string, audioId: string, noteContent: MediBytesNote) => void;
  onBusyChange?: (busy: boolean) => void;
  onTranscribingChange?: (transcribing: boolean) => void;
};

function looksLikeAudio(file: File): boolean {
  const name = file.name || "";
  const dot = name.lastIndexOf(".");
  if (dot >= 0) return AUDIO_EXTENSIONS.includes(name.slice(dot + 1).toLowerCase());
  return (file.type || "").toLowerCase().startsWith("audio/");
}

function newAudioId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function VoiceInput({ consentGranted, encounterId, disabled, onTranscript, onBusyChange, onTranscribingChange }: Props) {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState<TranscriptionJob | null>(null);
  const [retryUpload, setRetryUpload] = useState<RetryUpload | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const mountedRef = useRef(true);
  const callbacks = useRef({ onTranscript, onBusyChange, onTranscribingChange });
  callbacks.current = { onTranscript, onBusyChange, onTranscribingChange };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        recorder.onstop = null;
        recorder.stop();
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const busy = recording || transcribing;
  useEffect(() => callbacks.current.onBusyChange?.(busy), [busy]);
  useEffect(() => callbacks.current.onTranscribingChange?.(transcribing), [transcribing]);

  const transcribe = async (blob: Blob, filename: string, source: VoiceSource, audioId = newAudioId()) => {
    if (!encounterId) {
      setError("Open a consultation before submitting audio.");
      return;
    }
    const pending: RetryUpload = { blob, filename, source, audioId };
    setRetryUpload(null);
    setError("");
    setJob(null);
    setTranscribing(true);
    try {
      let current = await transcribeAudio(blob, filename, encounterId, audioId);
      for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
        if (!mountedRef.current) return;
        setJob(current);
        if (current.job_status === "failed") {
          setError(current.job_error || "MediBytes could not transcribe this recording.");
          if (current.can_retry_upload) setRetryUpload(pending);
          return;
        }
        if (current.job_status === "succeeded" && current.transcript) {
          setError("");
          setRetryUpload(null);
          if (!current.note_content) {
            setError(current.job_error || "MediBytes completed this recording without the required six-section note.");
            return;
          }
          callbacks.current.onTranscript(current.transcript, source, current.transcript_event_id || "", audioId, current.note_content);
          return;
        }
        await wait(POLL_INTERVAL_MS);
        if (!mountedRef.current) return;
        current = await getTranscription(audioId, encounterId);
      }
      setError(current.job_status === "succeeded"
        ? (current.job_error || "MediBytes completed this recording but has not returned its transcript yet. Check saved transcripts later.")
        : "MediBytes is still processing this recording. It remains attached to this consultation; check saved transcripts later.");
      setRetryUpload(pending);
    } catch (err: any) {
      if (!mountedRef.current) return;
      setError(String(err?.message || err));
      if (!(err instanceof ApiError) || err.status === 0 || err.status >= 500) setRetryUpload(pending);
    } finally {
      if (mountedRef.current) setTranscribing(false);
    }
  };

  const startRecording = async () => {
    setError("");
    if (!consentGranted) {
      setError(CONSENT_MESSAGE);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Audio capture is not available in this browser. Upload an audio file or paste the transcript instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        void transcribe(blob, "consultation.webm", "record");
      };
      recorder.start();
      recorderRef.current = recorder;
      streamRef.current = stream;
      setRecording(true);
    } catch (err: any) {
      setError(`Microphone unavailable: ${String(err?.message || err)}`);
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    setRecording(false);
  };

  const chooseFile = () => {
    setError("");
    if (!consentGranted) {
      setError(CONSENT_MESSAGE);
      return;
    }
    fileRef.current?.click();
  };

  const onFile = (file: File | undefined) => {
    if (!file) return;
    setError("");
    if (!looksLikeAudio(file)) {
      setError("Choose wav, mp3, m4a, mp4, aac, flac, ogg or webm audio.");
      return;
    }
    if (file.size > MAX_AUDIO_BYTES) {
      setError("Audio too large (max 64 MB).");
      return;
    }
    void transcribe(file, file.name, "upload");
  };

  const retry = () => {
    if (!retryUpload) return;
    void transcribe(retryUpload.blob, retryUpload.filename, retryUpload.source, retryUpload.audioId);
  };

  const currentStatus = job?.job_status === "running"
    ? "MediBytes is transcribing…"
    : job?.job_status === "queued"
      ? "Queued with MediBytes…"
      : job?.job_status === "succeeded"
        ? "Transcription completed; waiting for transcript delivery…"
        : "Submitting to MediBytes…";

  return (
    <div className="flex-col gap-1">
      <div className="button-row">
        {recording ? (
          <button type="button" className="btn btn-danger btn-sm" onClick={stopRecording}>Stop &amp; transcribe</button>
        ) : (
          <button type="button" className="btn btn-sm" onClick={startRecording} disabled={transcribing || disabled}>
            {transcribing ? <><span className="spinner" /> Checking status…</> : "Record audio"}
          </button>
        )}
        <button type="button" className="btn btn-sm" onClick={chooseFile} disabled={busy || disabled}>
          Upload voice
        </button>
        {retryUpload ? <button type="button" className="btn btn-sm" onClick={retry} disabled={transcribing || disabled}>Retry upload</button> : null}
        <input
          ref={fileRef}
          type="file"
          accept="audio/*,.mp3,.wav,.m4a,.mp4,.aac,.flac,.ogg,.webm"
          style={{ display: "none" }}
          onChange={(event) => {
            onFile(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </div>
      {transcribing ? <div className="small muted" role="status">{currentStatus}</div> : null}
      {error ? <div className="small" role="alert" style={{ color: "var(--danger, #b42318)" }}>{error}</div> : null}
    </div>
  );
}

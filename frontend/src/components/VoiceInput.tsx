import { useEffect, useRef, useState } from "react";
import { transcribeAudio } from "../api";
import type { Draft } from "../types";

// The only place in the app that captures voice. Record and Upload always come together: a screen that
// needs voice uses this component, so it cannot get one without the other.

const MAX_AUDIO_BYTES = 64 * 1024 * 1024;
const AUDIO_EXTENSIONS = ["mp3", "wav", "m4a", "webm", "ogg", "oga", "mp4", "mpeg", "mpga", "flac", "aac"];
export const CONSENT_MESSAGE = "Record patient consent before capturing audio.";

export type VoiceSource = "record" | "upload";

type Props = {
  /** Audio capture is blocked, for both Record and Upload, until this is true. */
  consentGranted: boolean;
  /** Another step (for example drafting) is running; both buttons wait. */
  disabled?: boolean;
  /** Called with the draft the MediBytes pipeline produced from the recording. */
  onDraft: (draft: Draft, source: VoiceSource) => void;
  /** True while recording or while the transcription request runs. */
  onBusyChange?: (busy: boolean) => void;
  /** True only while the transcription request runs ("Transcribing..."). */
  onTranscribingChange?: (transcribing: boolean) => void;
};

function looksLikeAudio(file: File): boolean {
  const name = file.name || "";
  const dot = name.lastIndexOf(".");
  if (dot >= 0) return AUDIO_EXTENSIONS.includes(name.slice(dot + 1).toLowerCase());
  return (file.type || "").toLowerCase().startsWith("audio/");
}

export function VoiceInput({ consentGranted, disabled, onDraft, onBusyChange, onTranscribingChange }: Props) {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const mountedRef = useRef(true);
  // Callbacks are read through a ref so a transcript that arrives later reaches the current handler.
  const callbacks = useRef({ onDraft, onBusyChange, onTranscribingChange });
  callbacks.current = { onDraft, onBusyChange, onTranscribingChange };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      // Leaving the screen drops the recording and any transcript still on its way.
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
  useEffect(() => {
    callbacks.current.onBusyChange?.(busy);
  }, [busy]);
  useEffect(() => {
    callbacks.current.onTranscribingChange?.(transcribing);
  }, [transcribing]);

  const transcribe = async (body: Blob, filename: string | undefined, source: VoiceSource) => {
    setTranscribing(true);
    try {
      const result = await transcribeAudio(body, filename);
      if (!mountedRef.current) return;
      setError("");
      callbacks.current.onDraft(result.draft, source);
    } catch (err: any) {
      if (mountedRef.current) setError(String(err?.message || err));
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
        void transcribe(blob, undefined, "record");
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
      setError("Choose an audio file (mp3, wav, m4a, webm or ogg).");
      return;
    }
    if (file.size > MAX_AUDIO_BYTES) {
      setError("Audio too large (max 64 MB).");
      return;
    }
    void transcribe(file, file.name, "upload");
  };

  return (
    <div className="flex-col gap-1">
      <div className="button-row">
        {recording ? (
          <button type="button" className="btn btn-danger btn-sm" onClick={stopRecording}>Stop & transcribe</button>
        ) : (
          <button type="button" className="btn btn-sm" onClick={startRecording} disabled={transcribing || disabled}>
            {transcribing ? <><span className="spinner" /> Transcribing...</> : "Record audio"}
          </button>
        )}
        <button type="button" className="btn btn-sm" onClick={chooseFile} disabled={busy || disabled}>
          Upload voice
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="audio/*,.mp3,.wav,.m4a,.webm,.ogg,.aac,.flac,.mp4"
          style={{ display: "none" }}
          onChange={(event) => {
            onFile(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </div>
      {error ? <div className="small" role="alert" style={{ color: "var(--danger, #b42318)" }}>{error}</div> : null}
    </div>
  );
}

export interface AudioSource {
  label: string;
  description: string;
  url: string;
  filename: string;
}

const ORIGINAL = /^input\.[a-z0-9]+$/i;
const CLEANED = "cleaned.wav";

export function isAudioArtefact(name: string): boolean {
  return ORIGINAL.test(name) || name === CLEANED;
}

/** Original upload (`input.*`) and the cleaned 16 kHz WAV, when the job kept them. */
export function audioSources(files: readonly string[], fileUrl: (name: string) => string): AudioSource[] {
  const sources: AudioSource[] = [];
  const original = files.find((f) => ORIGINAL.test(f));
  if (original) {
    sources.push({ label: "Original", description: "As uploaded", url: fileUrl(original), filename: original });
  }
  if (files.includes(CLEANED)) {
    sources.push({
      label: "Cleaned",
      description: "Mono 16 kHz, level-normalised (what MedASR heard)",
      url: fileUrl(CLEANED),
      filename: CLEANED,
    });
  }
  return sources;
}

export const ACCEPTED_EXTENSIONS = [
  ".wav",
  ".mp3",
  ".m4a",
  ".mp4",
  ".aac",
  ".flac",
  ".ogg",
  ".webm",
] as const;

export const MAX_UPLOAD_BYTES = 64 * 1024 * 1024;

/** Value for <input accept>. */
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(",");

export function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot < 0 ? "" : filename.slice(dot).toLowerCase();
}

/** Returns a user-facing reason the file cannot be uploaded, or null when it is acceptable. */
export function validateUpload(file: Pick<File, "name" | "size">): string | null {
  const ext = extensionOf(file.name);
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) {
    const shown = ext ? `${ext} files are` : "Files without an extension are";
    return `${shown} not supported. Use ${ACCEPTED_EXTENSIONS.join(", ")}.`;
  }
  if (file.size === 0) return "This file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) return "This file is larger than the 64 MB limit.";
  return null;
}

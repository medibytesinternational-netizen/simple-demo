// Frontend-only UI preview (Netlify). Enabled only when the build sets VITE_DEMO_MODE=true.
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

export const PREVIEW_LABEL = "Synthetic Demo — UI Preview Only";

export const PREVIEW_WRITE_MESSAGE =
  "UI preview: this action is disabled. Nothing is saved, approved or sent — there is no backend or hospital database in this demo.";

export const PREVIEW_SESSION_NOTE =
  "Preview only — kept in this browser tab and cleared on refresh. Not saved to any database.";

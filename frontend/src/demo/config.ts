// Frontend-only UI preview (Netlify). Enabled only when the build sets VITE_DEMO_MODE=true.
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

export const PREVIEW_LABEL = "MediBytes Preview";

export const PREVIEW_WRITE_MESSAGE =
  "This action is unavailable in the preview environment. Nothing is saved, approved or sent.";

export const PREVIEW_SESSION_NOTE =
  "Preview environment — changes remain in this browser tab and are cleared on refresh.";

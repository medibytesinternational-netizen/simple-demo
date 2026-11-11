// Frontend-only preview is the default because this repository no longer ships an API.
// Set VITE_DEMO_MODE=false only when pointing the UI at an external compatible API.
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== "false";

export const PREVIEW_LABEL = "MediBytes Preview";

export const PREVIEW_WRITE_MESSAGE =
  "This action is unavailable in the preview environment. Nothing is saved, approved or sent.";

export const PREVIEW_SESSION_NOTE =
  "Preview environment — changes remain in this browser tab and are cleared on refresh.";

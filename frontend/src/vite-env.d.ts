/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "true" builds the frontend-only UI preview (no backend requests). */
  readonly VITE_DEMO_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

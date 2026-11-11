/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "false" connects to an externally hosted compatible API; preview mode is the default. */
  readonly VITE_DEMO_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

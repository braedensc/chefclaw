/// <reference types="vite/client" />

// The ONLY env vars the client bundle may see (Hard Rule 4: server keys never
// appear as VITE_*). A Sentry DSN is an ingest address, not a credential —
// docs/STACK-RATIONALE.md "observability opt-in by env presence".
interface ImportMetaEnv {
  readonly VITE_SENTRY_DSN?: string;
  readonly VITE_SENTRY_ENVIRONMENT?: string;
  readonly VITE_SENTRY_RELEASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

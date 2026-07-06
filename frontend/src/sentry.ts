// DSN-gated Sentry init (V2-A ADR): no VITE_SENTRY_DSN at build time ⇒ the
// SDK is never initialised — dev, CI, and tests send zero events by
// construction. Error tracking only: tracing and replay stay off.

import * as Sentry from '@sentry/react';

export function maybeInitSentry(
  env: Pick<
    ImportMetaEnv,
    'VITE_SENTRY_DSN' | 'VITE_SENTRY_ENVIRONMENT' | 'VITE_SENTRY_RELEASE'
  > = import.meta.env,
): boolean {
  const dsn = env.VITE_SENTRY_DSN;
  if (!dsn) return false;
  Sentry.init({
    dsn,
    environment: env.VITE_SENTRY_ENVIRONMENT || 'local',
    release: env.VITE_SENTRY_RELEASE || undefined,
    sendDefaultPii: false,
    tracesSampleRate: 0,
  });
  return true;
}

// DSN-gating proof for the frontend (mirrors the backend test): no
// VITE_SENTRY_DSN ⇒ Sentry.init is never called — tests/CI send zero events.

import { describe, expect, it, vi } from 'vitest';

import { maybeInitSentry } from './sentry';

const init = vi.hoisted(() => vi.fn());
vi.mock('@sentry/react', () => ({ init }));

describe('maybeInitSentry', () => {
  it('never touches the SDK without a DSN', () => {
    expect(maybeInitSentry({})).toBe(false);
    expect(maybeInitSentry({ VITE_SENTRY_DSN: '' })).toBe(false);
    expect(init).not.toHaveBeenCalled();
  });

  it('initialises with environment + release and tracing off when a DSN is set', () => {
    const enabled = maybeInitSentry({
      VITE_SENTRY_DSN: 'https://examplekey@o0.ingest.example.test/2',
      VITE_SENTRY_ENVIRONMENT: 'vps',
      VITE_SENTRY_RELEASE: 'abc1234',
    });

    expect(enabled).toBe(true);
    expect(init).toHaveBeenCalledWith({
      dsn: 'https://examplekey@o0.ingest.example.test/2',
      environment: 'vps',
      release: 'abc1234',
      sendDefaultPii: false,
      tracesSampleRate: 0,
    });
  });

  it('defaults the environment to local', () => {
    init.mockClear();
    maybeInitSentry({ VITE_SENTRY_DSN: 'https://k@o0.ingest.example.test/2' });
    expect(init).toHaveBeenCalledWith(
      expect.objectContaining({ environment: 'local', release: undefined }),
    );
  });
});

import { useQuery } from '@tanstack/react-query';

import { ApiError } from '../api-error';
import { healthApiHealthGetOptions } from '../client/@tanstack/react-query.gen';

interface HealthPanelProps {
  onClearToken: () => void;
}

/**
 * Calls GET /api/health through the generated TanStack Query options and
 * renders the reported health. Failures are split into three distinct states
 * so debugging starts in the right place:
 *   - 401           → the token was rejected; clearing/re-entering it is the fix
 *   - other non-2xx → the API answered with an error; show the actual status
 *   - no response   → network failure; the stack probably is not running
 * (An ApiError carries the HTTP status; any other thrown error means the
 * request never got an HTTP response at all — see api-error.ts.)
 */
export function HealthPanel({ onClearToken }: HealthPanelProps) {
  const health = useQuery(healthApiHealthGetOptions());

  const status = health.error instanceof ApiError ? health.error.status : null;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <section className="w-full max-w-md rounded-xl border border-neutral-800 bg-neutral-900 p-6 shadow-lg">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-lg font-semibold text-neutral-100">API health</h1>
          <button
            type="button"
            onClick={onClearToken}
            className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:border-neutral-500 hover:text-neutral-100"
          >
            Clear token
          </button>
        </div>

        {health.isPending && (
          <p className="mt-4 text-sm text-neutral-400">Checking API health…</p>
        )}

        {health.isError && (
          <div className="mt-4 rounded-md border border-red-900 bg-red-950/40 p-4">
            {status === 401 ? (
              <>
                <p className="text-sm text-red-300">
                  Token rejected (401) — clear the token and re-enter it.
                </p>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={onClearToken}
                    className="rounded-md bg-red-800 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-700"
                  >
                    Clear token & re-enter
                  </button>
                  <button
                    type="button"
                    onClick={() => void health.refetch()}
                    className="rounded-md border border-red-800 px-3 py-1.5 text-xs text-red-200 hover:border-red-600"
                  >
                    Retry
                  </button>
                </div>
              </>
            ) : status !== null ? (
              <>
                <p className="text-sm text-red-300">
                  {`The API responded with an unexpected error (HTTP ${status}). Retry, or check the api container logs.`}
                </p>
                <button
                  type="button"
                  onClick={() => void health.refetch()}
                  className="mt-3 rounded-md bg-red-800 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-700"
                >
                  Retry
                </button>
              </>
            ) : (
              <>
                <p className="text-sm text-red-300">
                  Could not reach the API — is the stack running (docker compose
                  up)?
                </p>
                <button
                  type="button"
                  onClick={() => void health.refetch()}
                  className="mt-3 rounded-md bg-red-800 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-700"
                >
                  Retry
                </button>
              </>
            )}
          </div>
        )}

        {health.isSuccess && (
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-neutral-400">status</dt>
            <dd
              className={
                health.data.status === 'ok'
                  ? 'font-medium text-emerald-400'
                  : 'font-medium text-amber-400'
              }
            >
              {health.data.status}
            </dd>
            <dt className="text-neutral-400">db</dt>
            <dd
              className={
                health.data.db === 'ok'
                  ? 'font-medium text-emerald-400'
                  : 'font-medium text-amber-400'
              }
            >
              {health.data.db}
            </dd>
          </dl>
        )}
      </section>
    </div>
  );
}

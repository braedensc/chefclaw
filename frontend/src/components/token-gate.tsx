import { useCallback, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';

import { clearToken, getToken, saveToken } from '../token';
import { TokenContext } from '../token-context';

interface TokenGateProps {
  children: ReactNode;
}

/**
 * Gates the app on the API token: without one in localStorage it shows a
 * centered paste-your-token card; with one it renders its children inside a
 * TokenContext that exposes clearToken (used by the header button and the
 * 401 recovery paths). The token only ever lives in this browser's
 * localStorage.
 */
export function TokenGate({ children }: TokenGateProps) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [draft, setDraft] = useState('');

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    saveToken(trimmed);
    setTokenState(trimmed);
    setDraft('');
  }

  const handleClear = useCallback(() => {
    clearToken();
    setTokenState(null);
  }, []);

  const actions = useMemo(() => ({ clearToken: handleClear }), [handleClear]);

  if (token === null) {
    return (
      <main className="min-h-screen bg-neutral-950 text-neutral-100">
        <div className="flex min-h-screen items-center justify-center p-4">
          <form
            onSubmit={handleSubmit}
            className="w-full max-w-sm rounded-xl border border-neutral-800 bg-neutral-900 p-6 shadow-lg"
          >
            <h1 className="text-lg font-semibold text-neutral-100">chefclaw</h1>
            <p className="mt-2 text-sm text-neutral-400">
              Paste your CHEFCLAW_API_TOKEN — stored only in this browser
            </p>
            <label className="sr-only" htmlFor="api-token">
              API token
            </label>
            <input
              id="api-token"
              type="password"
              autoComplete="off"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="API token"
              className="mt-4 w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-600 focus:border-emerald-500 focus:outline-none"
            />
            <button
              type="submit"
              className="mt-4 w-full rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500"
            >
              Save token
            </button>
          </form>
        </div>
      </main>
    );
  }

  return (
    <TokenContext.Provider value={actions}>{children}</TokenContext.Provider>
  );
}

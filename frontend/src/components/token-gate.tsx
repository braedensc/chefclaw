import { useState } from 'react';
import type { FormEvent } from 'react';

import { clearToken, getToken, saveToken } from '../token';
import { HealthPanel } from './health-panel';

/**
 * Gates the app on the API token: without one in localStorage it shows a
 * centered paste-your-token card; with one it renders the HealthPanel.
 * The token only ever lives in this browser's localStorage.
 */
export function TokenGate() {
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

  function handleClear() {
    clearToken();
    setTokenState(null);
  }

  if (token === null) {
    return (
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
    );
  }

  return <HealthPanel onClearToken={handleClear} />;
}

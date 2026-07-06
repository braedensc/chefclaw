import { useCallback, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';

import { clearToken, getToken, saveToken } from '../token';
import { TokenContext } from '../token-context';
import { PuppyChef } from './brand/puppy-chef';

interface TokenGateProps {
  children: ReactNode;
}

/**
 * Gates the app on the API token: without one in localStorage it shows the
 * first-run night-kitchen welcome (mockup B's "token gate" vignette); with
 * one it renders its children inside a TokenContext that exposes clearToken
 * (used by the header button and the 401 recovery paths). The token only
 * ever lives in this browser's localStorage.
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
      <main className="text-ink flex min-h-screen items-center justify-center p-4">
        <form
          onSubmit={handleSubmit}
          className="rounded-card border-line bg-panel-deep relative w-full max-w-md border px-6 pt-9 pb-6 sm:px-8"
        >
          <span className="rounded-chip border-line-bright bg-night text-ink-faint absolute -top-2.5 left-4 border px-2.5 py-0.5 font-display text-[9.5px] font-bold tracking-[0.24em] uppercase">
            Token gate · first run
          </span>
          <PuppyChef
            variant="hero"
            animated
            size={150}
            className="mx-auto block"
            label="The chefclaw puppy chef, waving hello"
          />
          <h1 className="text-warm glow-text-warm mt-3 text-center font-display text-lg font-extrabold tracking-[0.22em] uppercase">
            Welcome to the night kitchen{' '}
            {/* whitespace-nowrap: the ZH greeting must never break mid-phrase */}
            <span
              lang="zh"
              className="text-gold glow-text-gold font-body text-base font-medium tracking-[0.1em] whitespace-nowrap normal-case"
            >
              · 欢迎光临
            </span>
          </h1>
          <p className="text-ink-dim mt-3 text-center text-sm leading-relaxed">
            chefclaw watches the cooking video, then writes the dish down
            properly — bilingual, structured, yours to keep.
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
            placeholder="paste token to open the stall"
            className="rounded-field border-line-bright bg-night text-ink placeholder:text-ink-faint focus:border-gold focus:glow-gold mt-5 h-11 w-full border px-4 font-mono text-sm tracking-[0.12em] focus:outline-none"
          />
          <button
            type="submit"
            className="rounded-field border-gold/65 bg-gold/10 text-warm glow-gold glow-text-gold hover:bg-gold/20 mt-3 h-11 w-full border font-display text-sm font-bold tracking-[0.16em] uppercase transition-colors"
          >
            Save token
          </button>
          <p className="text-ink-faint mt-4 text-center text-[11px]">
            Paste your CHEFCLAW_API_TOKEN — stored only in this browser
          </p>
        </form>
      </main>
    );
  }

  return (
    <TokenContext.Provider value={actions}>{children}</TokenContext.Provider>
  );
}

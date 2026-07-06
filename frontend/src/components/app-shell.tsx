import { Link } from '@tanstack/react-router';
import { useState } from 'react';
import type { ReactNode } from 'react';

import { useTokenActions } from '../token-context';
import { JobsDrawer } from './jobs-drawer';

/**
 * The chrome around every token-gated screen: header (title, Jobs drawer
 * toggle, Clear token) and the slide-over jobs panel.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { clearToken } = useTokenActions();
  const [jobsOpen, setJobsOpen] = useState(false);

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <header className="sticky top-0 z-20 border-b border-neutral-800 bg-neutral-950/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-4 px-4">
          <Link to="/" className="text-lg font-semibold tracking-tight">
            chefclaw
          </Link>
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-expanded={jobsOpen}
              onClick={() => setJobsOpen((open) => !open)}
              className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:border-neutral-500 hover:text-neutral-100"
            >
              Jobs
            </button>
            <button
              type="button"
              onClick={clearToken}
              className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:border-neutral-500 hover:text-neutral-100"
            >
              Clear token
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      {jobsOpen && <JobsDrawer onClose={() => setJobsOpen(false)} />}
    </div>
  );
}

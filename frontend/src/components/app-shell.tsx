import { Link } from '@tanstack/react-router';
import { useState } from 'react';
import type { ReactNode } from 'react';

import { useTokenActions } from '../token-context';
import { PuppyChef } from './brand/puppy-chef';
import { JobsDrawer } from './jobs-drawer';

/** Quiet caps text control — the shared look for the header's right-side nav. */
const HEADER_CONTROL =
  'px-0.5 py-1.5 font-display text-[11px] font-semibold whitespace-nowrap uppercase tracking-[0.1em] text-ink-faint transition-colors hover:text-cyan hover:glow-text-cyan sm:px-2 sm:text-[11.5px] sm:tracking-[0.2em]';

/**
 * The chrome around every token-gated screen: the neon storefront header
 * (puppy mark, split wordmark, bilingual tagline, Jobs drawer toggle, Clear
 * token) and the slide-over jobs panel.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { clearToken } = useTokenActions();
  const [jobsOpen, setJobsOpen] = useState(false);

  return (
    <div className="min-h-screen text-ink">
      <header className="sticky top-0 z-20 border-b border-line bg-night/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-2 px-4 sm:gap-4">
          {/* aria-label keeps the home link's accessible name a stable
              "chefclaw" — the visible wordmark uppercases via CSS. */}
          <Link
            to="/"
            aria-label="chefclaw"
            className="flex items-center gap-2.5"
          >
            <PuppyChef
              variant="mark"
              size={44}
              className="glow-drop-chili h-auto w-9 sm:w-11"
            />
            <span className="flex flex-col gap-1">
              <span className="font-display text-[21px] leading-none font-extrabold tracking-[0.17em] uppercase sm:text-[26px]">
                <span className="text-warm glow-text-warm">chef</span>
                <span className="text-chili-bright glow-text-chili">claw</span>
              </span>
              <span className="text-ink-faint hidden font-display text-[9.5px] leading-none font-semibold tracking-[0.34em] uppercase sm:block">
                <span
                  lang="zh"
                  className="font-body font-medium tracking-[0.22em] text-[#8a7a58]"
                >
                  夜市厨房
                </span>{' '}
                · night-market kitchen
              </span>
            </span>
          </Link>
          <nav className="flex items-center gap-0.5 sm:gap-1">
            {/* A LINK named "Settings" — the golden selector contract's
                button "Jobs" (e2e/golden) stays the only header button
                with that accessible name. */}
            <Link to="/settings" className={HEADER_CONTROL}>
              Settings
            </Link>
            <span aria-hidden="true" className="text-line-bright">
              ·
            </span>
            <button
              type="button"
              aria-expanded={jobsOpen}
              onClick={() => setJobsOpen((open) => !open)}
              className={HEADER_CONTROL}
            >
              Jobs
            </button>
            <span aria-hidden="true" className="text-line-bright">
              ·
            </span>
            <button
              type="button"
              onClick={clearToken}
              className={HEADER_CONTROL}
            >
              Clear token
            </button>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      {jobsOpen && <JobsDrawer onClose={() => setJobsOpen(false)} />}
    </div>
  );
}

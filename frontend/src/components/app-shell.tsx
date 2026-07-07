import { Link } from '@tanstack/react-router';
import { useState } from 'react';
import type { ReactNode } from 'react';

import { useAuth } from '../auth-context';
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
  const { me, signOut } = useAuth();
  const [jobsOpen, setJobsOpen] = useState(false);

  return (
    <div className="min-h-screen text-ink">
      <header className="relative sticky top-0 z-20 border-b border-line bg-night/95 backdrop-blur">
        {/* always-on neon underglow along the header's bottom edge — a small
            persistent lit element so the storefront reads as "open" even with
            no active job; fades to transparent at the corners like a tube. */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 h-px opacity-50"
          style={{
            background:
              'linear-gradient(90deg, transparent, color-mix(in srgb, var(--color-cyan) 50%, transparent) 30%, color-mix(in srgb, var(--color-chili) 42%, transparent) 70%, transparent)',
            boxShadow:
              '0 1px 12px color-mix(in srgb, var(--color-cyan) 22%, transparent)',
          }}
        />
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
                {/* the storefront's "open" pip — a small always-lit sign so the
                    header reads as live even at rest (decorative, not a jobs
                    badge). */}
                <span
                  aria-hidden="true"
                  className="ml-1.5 inline-block h-[7px] w-[7px] rounded-full bg-gold align-middle"
                  style={{
                    boxShadow:
                      '0 0 8px 1px color-mix(in srgb, var(--color-gold) 80%, transparent)',
                  }}
                />
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
            {/* Admin nav is COSMETIC-gated on me.is_admin (critique M9): the
                server enforces admin access at the transport layer, so hiding
                the link is convenience, not security. */}
            {me.is_admin && (
              <>
                <Link to="/admin/invites" className={HEADER_CONTROL}>
                  Admin
                </Link>
                <span aria-hidden="true" className="text-line-bright">
                  ·
                </span>
              </>
            )}
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
            {/* The account control: the signed-in email is the button's
                accessible title; clicking signs out (kills the session
                server-side, returns to the login gate). */}
            <button
              type="button"
              onClick={signOut}
              title={me.email}
              className={HEADER_CONTROL}
            >
              Sign out
            </button>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      {jobsOpen && <JobsDrawer onClose={() => setJobsOpen(false)} />}
    </div>
  );
}

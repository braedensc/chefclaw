import { useRouterState } from '@tanstack/react-router';

import { PuppyChef } from './brand/puppy-chef';

/** Sign-in failure codes the server callback may bounce back on
 * (`302 → /login?error=…`, routers/auth.py). `denied` is deliberately opaque —
 * every who-may-sign-in rejection maps to it (critique M6), so the copy never
 * distinguishes "no invite" from "email mismatch". */
type AuthError = 'expired' | 'denied';

function readAuthError(raw: unknown): AuthError | null {
  return raw === 'expired' || raw === 'denied' ? raw : null;
}

/**
 * The unauthenticated gate (M2): a full-page night-kitchen welcome with a
 * single "Sign in with Google" action. The button is a FULL-PAGE navigation to
 * the SERVER OAuth entrypoint — the SPA never touches Google or sees a token.
 * Rendered by the AuthGate when /api/me is unauthenticated, and by the /login
 * route directly. `sessionEnded` softens the copy after a logout / expiry; an
 * `?error=` code (set by the callback on a failed sign-in) surfaces a banner so
 * a benign expiry no longer dead-ends on raw JSON.
 */
export function LoginPage({
  sessionEnded = false,
}: {
  sessionEnded?: boolean;
}) {
  const search = useRouterState({ select: (s) => s.location.search }) as {
    error?: unknown;
  };
  const authError = readAuthError(search.error);

  function signIn() {
    window.location.href = '/api/auth/google/login?next=%2F';
  }

  return (
    <main className="text-ink flex min-h-screen items-center justify-center p-4">
      <div className="rounded-card border-line bg-panel-deep relative w-full max-w-md border px-6 pt-9 pb-6 text-center sm:px-8">
        <span className="rounded-chip border-line-bright bg-night text-ink-faint absolute -top-2.5 left-4 border px-2.5 py-0.5 font-display text-[9.5px] font-bold tracking-[0.24em] uppercase">
          {sessionEnded ? 'Signed out' : 'Invite only · sign in'}
        </span>
        <PuppyChef
          variant="hero"
          animated
          size={150}
          className="mx-auto block"
          label="The chefclaw puppy chef, waving hello"
        />
        <h1 className="text-warm glow-text-warm mt-3 font-display text-lg font-extrabold tracking-[0.22em] uppercase">
          Welcome to the night kitchen{' '}
          <span
            lang="zh"
            className="text-gold glow-text-gold font-body text-base font-medium tracking-[0.1em] whitespace-nowrap normal-case"
          >
            · 欢迎光临
          </span>
        </h1>
        <p className="text-ink-dim mt-3 text-sm leading-relaxed">
          {sessionEnded
            ? 'Your session ended. Sign in again to get back to your cookbook.'
            : 'chefclaw watches the cooking video, then writes the dish down properly — bilingual, structured, yours to keep.'}
        </p>
        {authError && (
          <p
            role="alert"
            className={`rounded-field mt-5 border px-3.5 py-2.5 text-left text-xs leading-snug ${
              authError === 'denied'
                ? 'border-chili/40 bg-chili/5 text-chili-bright'
                : 'border-line-bright bg-night text-ink-dim'
            }`}
          >
            {authError === 'denied'
              ? 'Sign-in isn’t available for this account. Contact the owner if you think this is a mistake.'
              : 'Your sign-in link expired before it completed. Please sign in again.'}
          </p>
        )}
        <button
          type="button"
          onClick={signIn}
          className="rounded-field border-gold/65 bg-gold/10 text-warm glow-gold glow-text-gold hover:bg-gold/20 mt-6 h-11 w-full border font-display text-sm font-bold tracking-[0.16em] uppercase transition-colors"
        >
          Sign in with Google
        </button>
        <p className="text-ink-faint mt-4 text-[11px]">
          Signup is invite-only — sign in with an invited Google account.
        </p>
      </div>
    </main>
  );
}

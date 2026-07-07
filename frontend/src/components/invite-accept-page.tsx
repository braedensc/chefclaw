import { useQuery } from '@tanstack/react-query';
import { useParams } from '@tanstack/react-router';

import { publicInviteApiInvitesTokenGetOptions } from '../client/@tanstack/react-query.gen';
import { PuppyChef } from './brand/puppy-chef';

/**
 * Public invite-accept page (/invite/:token). Reads GET /api/invites/{token}
 * (which returns a uniform 'invalid' shape for any missing/expired/revoked
 * token — no address leak, M13) and, for a live pending invite, shows who it's
 * for and a "Sign in with Google" full-page nav that activates the account via
 * the OAuth callback's invite gate.
 */
export function InviteAcceptPage() {
  const { token } = useParams({ from: '/invite/$token' });
  const invite = useQuery(
    publicInviteApiInvitesTokenGetOptions({ path: { token } }),
  );

  function signIn() {
    window.location.href = '/api/auth/google/login?next=%2F';
  }

  const isPending = invite.isSuccess && invite.data.status === 'pending';
  const isInvalid =
    invite.isError || (invite.isSuccess && invite.data.status !== 'pending');

  return (
    <main className="text-ink flex min-h-screen items-center justify-center p-4">
      <div className="rounded-card border-line bg-panel-deep relative w-full max-w-md border px-6 pt-9 pb-6 text-center sm:px-8">
        <span className="rounded-chip border-line-bright bg-night text-ink-faint absolute -top-2.5 left-4 border px-2.5 py-0.5 font-display text-[9.5px] font-bold tracking-[0.24em] uppercase">
          Invitation
        </span>
        <PuppyChef
          variant="hero"
          animated
          size={140}
          className="mx-auto block"
          label="The chefclaw puppy chef, waving hello"
        />

        {invite.isPending && (
          <p className="text-ink-dim mt-4 text-sm">Checking your invite…</p>
        )}

        {isInvalid && (
          <>
            <h1 className="text-warm mt-3 font-display text-lg font-extrabold tracking-[0.18em] uppercase">
              Invite not valid
            </h1>
            <p className="text-ink-dim mt-3 text-sm leading-relaxed">
              This invite link is invalid, already used, or expired. Ask the
              chefclaw owner to send you a fresh one.
            </p>
          </>
        )}

        {isPending && (
          <>
            <h1 className="text-warm glow-text-warm mt-3 font-display text-lg font-extrabold tracking-[0.2em] uppercase">
              You're invited
            </h1>
            <p className="text-ink-dim mt-3 text-sm leading-relaxed">
              This invite is for{' '}
              <span className="text-ink font-medium">{invite.data.email}</span>.
              Sign in with that Google account to activate your cookbook.
            </p>
            <button
              type="button"
              onClick={signIn}
              className="rounded-field border-gold/65 bg-gold/10 text-warm glow-gold glow-text-gold hover:bg-gold/20 mt-6 h-11 w-full border font-display text-sm font-bold tracking-[0.16em] uppercase transition-colors"
            >
              Sign in with Google
            </button>
          </>
        )}
      </div>
    </main>
  );
}

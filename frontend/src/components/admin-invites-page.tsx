import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { FormEvent } from 'react';

import { ApiError } from '../api-error';
import { useAuth } from '../auth-context';
import {
  createInviteApiAdminInvitesPostMutation,
  listInvitesApiAdminInvitesGetOptions,
  listInvitesApiAdminInvitesGetQueryKey,
  listUsersApiAdminUsersGetOptions,
  listUsersApiAdminUsersGetQueryKey,
  revokeInviteApiAdminInvitesInviteIdRevokePostMutation,
  setUserRealCoversApiAdminUsersUserIdPatchMutation,
} from '../client/@tanstack/react-query.gen';
import type { UserAdminRow } from '../client/types.gen';
import { CHILI_BTN, CYAN_BTN } from '../lib/button-styles';

const STATUS_CLASS: Record<string, string> = {
  pending: 'text-cyan',
  accepted: 'text-gold',
  revoked: 'text-ink-faint',
};

function createErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return 'That email is already a member.';
    if (error.status === 422) return "That doesn't look like a valid email.";
    if (error.status === 502)
      return 'The invite email could not be sent — try again.';
    if (error.status === 503)
      return 'Email/invite config is incomplete on the server.';
    return `Could not create the invite (HTTP ${error.status}).`;
  }
  return 'Could not reach the API.';
}

/**
 * Admin invite management (/admin/invites). COSMETIC-gated on me.is_admin — the
 * server enforces admin access on every /api/admin/* route (critique M9), so a
 * non-admin who reaches this page is shown a notice and every request 403s
 * anyway. Issue an invite (email is sent; the dev activation link is surfaced
 * when the server uses the fake console email adapter), see the roster, revoke.
 */
export function AdminInvitesPage() {
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState('');
  const [devLink, setDevLink] = useState<string | null>(null);

  const invites = useQuery(listInvitesApiAdminInvitesGetOptions());
  const invalidate = () =>
    void queryClient.invalidateQueries({
      queryKey: listInvitesApiAdminInvitesGetQueryKey(),
    });

  const create = useMutation({
    ...createInviteApiAdminInvitesPostMutation(),
    onSuccess: (data) => {
      setDevLink(data.dev_activation_link ?? null);
      setEmail('');
      invalidate();
    },
  });

  const revoke = useMutation({
    ...revokeInviteApiAdminInvitesInviteIdRevokePostMutation(),
    onSuccess: () => invalidate(),
  });

  if (!me.is_admin) {
    return (
      <div className="mx-auto max-w-2xl">
        <h1 className="text-warm font-display text-[22px] font-extrabold tracking-[0.24em] uppercase">
          Invites
        </h1>
        <p className="text-ink-dim mt-4 text-sm">
          You don't have access to invite management.
        </p>
      </div>
    );
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;
    setDevLink(null);
    create.mutate({ body: { email: trimmed } });
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-warm glow-text-warm font-display text-[22px] font-extrabold tracking-[0.24em] uppercase">
        Invites
      </h1>
      <p className="text-ink-faint mt-1 font-display text-[10px] font-semibold tracking-[0.3em] uppercase">
        invite-only · friends of the kitchen
      </p>

      <form
        onSubmit={handleSubmit}
        aria-label="Send an invite"
        className="rounded-card border-line bg-panel mt-4 border p-5"
      >
        <label
          htmlFor="invite-email"
          className="text-ink-faint font-display text-[11px] font-bold tracking-[0.28em] uppercase"
        >
          Invite an email
        </label>
        <div className="mt-3 flex gap-2">
          <input
            id="invite-email"
            type="email"
            autoComplete="off"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="friend@example.com"
            className="rounded-field border-line-bright bg-night text-ink placeholder:text-ink-faint focus:border-gold h-11 flex-1 border px-4 text-sm focus:outline-none"
          />
          <button
            type="submit"
            disabled={create.isPending}
            className={CYAN_BTN}
          >
            {create.isPending ? 'Sending…' : 'Send invite'}
          </button>
        </div>
        {create.isError && (
          <p className="text-chili-bright mt-3 text-sm">
            {createErrorMessage(create.error)}
          </p>
        )}
        {devLink !== null && (
          <p className="text-ink-dim mt-3 text-xs">
            Dev activation link (fake email — the real one is sent by SES):{' '}
            <a href={devLink} className="text-cyan break-all underline">
              {devLink}
            </a>
          </p>
        )}
      </form>

      <section
        aria-label="Invites"
        className="rounded-card border-line bg-panel mt-4 border p-5"
      >
        <h2 className="text-ink-faint font-display text-[11px] font-bold tracking-[0.28em] uppercase">
          Roster
        </h2>
        {invites.isPending && (
          <p className="text-ink-dim mt-3 text-sm">Loading invites…</p>
        )}
        {invites.isError && (
          <p className="text-ink-dim mt-3 text-sm">
            Could not load invites (are you signed in as an admin?).
          </p>
        )}
        {invites.isSuccess && invites.data.items.length === 0 && (
          <p className="text-ink-dim mt-3 text-sm">
            No invites yet — send one above.
          </p>
        )}
        {invites.isSuccess && invites.data.items.length > 0 && (
          <ul className="mt-3 space-y-2 text-sm">
            {invites.data.items.map((invite) => (
              <li
                key={invite.id}
                className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1"
              >
                <span className="text-ink">{invite.email}</span>
                <span className="flex items-center gap-3">
                  <span
                    className={`font-medium ${STATUS_CLASS[invite.status] ?? 'text-ink-dim'}`}
                  >
                    {invite.status}
                  </span>
                  {invite.status === 'pending' && (
                    <button
                      type="button"
                      onClick={() =>
                        revoke.mutate({ path: { invite_id: invite.id } })
                      }
                      className={CHILI_BTN}
                    >
                      Revoke
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <MembersSection />
    </div>
  );
}

/**
 * Members roster + the per-user PRIVATE real-frame cover grant (V2-F). A frame
 * only ever reaches a granted user AND only when the server runs with
 * CHEFCLAW_REAL_COVERS on — both default off, so this toggle is inert until the
 * operator enables real covers globally. Only the owner (admin) sees this; the
 * server enforces admin on every /api/admin/* route.
 */
function MembersSection() {
  const queryClient = useQueryClient();
  const users = useQuery(listUsersApiAdminUsersGetOptions());
  const setRealCovers = useMutation({
    ...setUserRealCoversApiAdminUsersUserIdPatchMutation(),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: listUsersApiAdminUsersGetQueryKey(),
      }),
  });

  function toggle(user: UserAdminRow) {
    setRealCovers.mutate({
      path: { user_id: user.id },
      body: { real_covers_enabled: !user.real_covers_enabled },
    });
  }

  return (
    <section
      aria-label="Members"
      className="rounded-card border-line bg-panel mt-4 border p-5"
    >
      <h2 className="text-ink-faint font-display text-[11px] font-bold tracking-[0.28em] uppercase">
        Members · real-frame covers
      </h2>
      <p className="text-ink-dim mt-2 text-xs">
        Real dish-photo covers are private and off by default. A member only
        sees them when granted here <em>and</em> the server runs with real
        covers enabled; everyone else always sees the illustrated sprite.
      </p>
      {users.isPending && (
        <p className="text-ink-dim mt-3 text-sm">Loading members…</p>
      )}
      {users.isError && (
        <p className="text-ink-dim mt-3 text-sm">
          Could not load members (are you signed in as an admin?).
        </p>
      )}
      {users.isSuccess && (
        <ul className="mt-3 space-y-2 text-sm">
          {users.data.items.map((user) => (
            <li
              key={user.id}
              className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1"
            >
              <span className="text-ink">
                {user.email}
                {user.is_admin && (
                  <span className="text-gold ml-2 font-display text-[9.5px] font-semibold tracking-[0.18em] uppercase">
                    owner
                  </span>
                )}
              </span>
              <label className="text-ink-dim flex cursor-pointer items-center gap-2 text-xs select-none">
                <input
                  type="checkbox"
                  checked={user.real_covers_enabled}
                  disabled={setRealCovers.isPending}
                  onChange={() => toggle(user)}
                  className="accent-cyan h-4 w-4"
                />
                real covers
              </label>
            </li>
          ))}
        </ul>
      )}
      {setRealCovers.isError && (
        <p role="alert" className="text-chili-bright mt-3 text-sm">
          Could not update that grant — try again.
        </p>
      )}
    </section>
  );
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { FormEvent } from 'react';

import { ApiError } from '../api-error';
import { useAuth } from '../auth-context';
import {
  adminSpendApiAdminSpendGetOptions,
  adminSpendApiAdminSpendGetQueryKey,
  createInviteApiAdminInvitesPostMutation,
  listInvitesApiAdminInvitesGetOptions,
  listInvitesApiAdminInvitesGetQueryKey,
  listUsersApiAdminUsersGetOptions,
  listUsersApiAdminUsersGetQueryKey,
  revokeInviteApiAdminInvitesInviteIdRevokePostMutation,
  setUserRealCoversApiAdminUsersUserIdPatchMutation,
  updateUserBudgetApiAdminUsersUserIdBudgetPatchMutation,
} from '../client/@tanstack/react-query.gen';
import type {
  AdminUserSpend,
  UserAdminRow,
  UserBudgetPatch,
} from '../client/types.gen';
import { CHILI_BTN, CYAN_BTN } from '../lib/button-styles';

const STATUS_CLASS: Record<string, string> = {
  pending: 'text-cyan',
  accepted: 'text-gold',
  revoked: 'text-ink-faint',
};

/** The quiet ghost affordance — matches the compact reset buttons elsewhere. */
const GHOST_BTN =
  'tap-target rounded-field border border-line-bright px-3.5 py-1.5 font-display text-xs font-semibold uppercase tracking-[0.16em] text-ink-dim transition hover:border-cyan/55 hover:text-cyan disabled:opacity-50';

/** Number field — `tap-field` floors it to ≥44px on coarse pointers (V2-C). */
const NUM_INPUT =
  'tap-field rounded-field border-line-bright bg-night text-ink placeholder:text-ink-faint focus:border-gold h-11 w-full border px-3 text-sm focus:outline-none';

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
 * The owner's admin console (/admin/invites). One place to invite friends, grant
 * private real-frame covers, tune each member's spend caps + paid tier, and watch
 * cross-user spend — no curl required. COSMETIC-gated on me.is_admin: the server
 * enforces admin on every /api/admin/* route (critique M9), so a non-admin who
 * reaches this page is shown a notice and every request 403s anyway.
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
          Admin
        </h1>
        <p className="text-ink-dim mt-4 text-sm">
          You don't have access to the admin console.
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
        Admin
      </h1>
      <p className="text-ink-faint mt-1 font-display text-[10px] font-semibold tracking-[0.3em] uppercase">
        invites · members · budgets &amp; tier · spend
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
      <BudgetsSection />
      <AdminSpendSection />
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

/**
 * Per-user cost controls (M3): monthly budget, daily attempt cap, and the paid
 * Gemini tier — the write side of the caps that GET /api/admin/spend reports.
 * Reads the same rollup so each member is shown with the spend + effective cap
 * it's being tuned against; the budget PATCH is a partial update, so a blank cap
 * is left untouched and "Use global" clears the override back to the env default.
 */
function BudgetsSection() {
  const spend = useQuery(adminSpendApiAdminSpendGetOptions());
  return (
    <section
      aria-label="Budgets & tier"
      className="rounded-card border-line bg-panel mt-4 border p-5"
    >
      <h2 className="text-ink-faint font-display text-[11px] font-bold tracking-[0.28em] uppercase">
        Budgets &amp; tier
      </h2>
      <p className="text-ink-dim mt-2 text-xs">
        Set a member's monthly budget and daily attempt cap (positive numbers
        only; leave a field blank to keep it). <em>Use global</em> clears an
        override back to the server default. Paid tier swaps that account onto
        the paid Gemini model within its budget.
      </p>
      {spend.isPending && (
        <p className="text-ink-dim mt-3 text-sm">Loading budgets…</p>
      )}
      {spend.isError && (
        <p className="text-ink-dim mt-3 text-sm">
          Could not load budgets (are you signed in as an admin?).
        </p>
      )}
      {spend.isSuccess && (
        <ul className="mt-3 space-y-3">
          {spend.data.users.map((user) => (
            <BudgetRow key={user.id} user={user} />
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * One member's editable caps + paid tier. The caps ride a small form (explicit
 * Save so a positive-only validation can gate the write); the paid tier is an
 * instant toggle, mirroring the real-covers grant. All three go through the same
 * budget PATCH and invalidate the spend rollup on success.
 */
function BudgetRow({ user }: { user: AdminUserSpend }) {
  const queryClient = useQueryClient();
  const [monthly, setMonthly] = useState('');
  const [daily, setDaily] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);

  const budget = useMutation({
    ...updateUserBudgetApiAdminUsersUserIdBudgetPatchMutation(),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: adminSpendApiAdminSpendGetQueryKey(),
      }),
  });

  function patch(body: UserBudgetPatch, onDone?: () => void) {
    budget.mutate({ path: { user_id: user.id }, body }, { onSuccess: onDone });
  }

  function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: UserBudgetPatch = {};
    const monthlyTrimmed = monthly.trim();
    if (monthlyTrimmed !== '') {
      const value = Number(monthlyTrimmed);
      if (!Number.isFinite(value) || value <= 0) {
        setValidationError('Monthly budget must be a positive dollar amount.');
        return;
      }
      body.monthly_budget_usd = value;
    }
    const dailyTrimmed = daily.trim();
    if (dailyTrimmed !== '') {
      const value = Number(dailyTrimmed);
      if (!Number.isInteger(value) || value <= 0) {
        setValidationError('Daily cap must be a positive whole number.');
        return;
      }
      body.max_attempts_per_day = value;
    }
    if (Object.keys(body).length === 0) {
      setValidationError('Enter a new budget or cap to save.');
      return;
    }
    setValidationError(null);
    patch(body, () => {
      setMonthly('');
      setDaily('');
    });
  }

  function handleUseGlobal() {
    setValidationError(null);
    patch({ monthly_budget_usd: null, max_attempts_per_day: null }, () => {
      setMonthly('');
      setDaily('');
    });
  }

  function handleTogglePaid() {
    setValidationError(null);
    patch({ paid_tier: !user.paid_tier });
  }

  const effectiveBudget = user.budget_monthly_usd ?? null;
  const effectiveDailyCap = user.daily_attempt_cap ?? null;
  const budgetPlaceholder =
    effectiveBudget !== null ? effectiveBudget.toFixed(2) : 'global';
  const dailyPlaceholder =
    effectiveDailyCap !== null ? String(effectiveDailyCap) : 'global';

  return (
    <li className="rounded-field border-line bg-night/40 border p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-ink flex items-center gap-2">
          {user.email}
          {user.paid_tier && (
            <span className="text-gold text-xs font-medium">paid</span>
          )}
        </span>
        <span className="text-ink-faint text-xs">
          ${user.month_to_date_usd.toFixed(2)} spent
          {effectiveBudget !== null && ` of $${effectiveBudget.toFixed(2)}`}
          {user.cap_is_personal ? ' (personal)' : ' (global)'}
          {' · '}
          {user.attempts_today}
          {effectiveDailyCap !== null && `/${effectiveDailyCap}`} today
        </span>
      </div>

      <form
        onSubmit={handleSave}
        aria-label={`Budget for ${user.email}`}
        className="mt-3 flex flex-wrap items-end gap-3"
      >
        <div className="flex-1 basis-32">
          <label
            htmlFor={`budget-${user.id}`}
            className="text-ink-faint font-display text-[10px] font-bold tracking-[0.2em] uppercase"
          >
            Monthly budget ($)
          </label>
          <input
            id={`budget-${user.id}`}
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            value={monthly}
            disabled={budget.isPending}
            onChange={(e) => setMonthly(e.target.value)}
            placeholder={budgetPlaceholder}
            className={`mt-1 ${NUM_INPUT}`}
          />
        </div>
        <div className="flex-1 basis-28">
          <label
            htmlFor={`daily-${user.id}`}
            className="text-ink-faint font-display text-[10px] font-bold tracking-[0.2em] uppercase"
          >
            Attempts / day
          </label>
          <input
            id={`daily-${user.id}`}
            type="number"
            inputMode="numeric"
            min="1"
            step="1"
            value={daily}
            disabled={budget.isPending}
            onChange={(e) => setDaily(e.target.value)}
            placeholder={dailyPlaceholder}
            className={`mt-1 ${NUM_INPUT}`}
          />
        </div>
        <button type="submit" disabled={budget.isPending} className={CYAN_BTN}>
          Save
        </button>
        <button
          type="button"
          onClick={handleUseGlobal}
          disabled={budget.isPending}
          className={GHOST_BTN}
        >
          Use global
        </button>
      </form>

      <label className="text-ink-dim tap-target mt-2 flex cursor-pointer items-center gap-2 text-xs select-none">
        <input
          type="checkbox"
          checked={user.paid_tier}
          disabled={budget.isPending}
          onChange={handleTogglePaid}
          className="accent-gold h-4 w-4"
        />
        Paid model tier
      </label>

      {validationError && (
        <p role="alert" className="text-chili-bright mt-2 text-sm">
          {validationError}
        </p>
      )}
      {budget.isError && (
        <p role="alert" className="text-chili-bright mt-2 text-sm">
          Could not update that budget — try again.
        </p>
      )}
    </li>
  );
}

/**
 * Cross-user spend rollup (GET /api/admin/spend) — the admin view the per-user
 * caps (M3) made necessary: every member's month-to-date spend against their
 * EFFECTIVE cap, plus tenant totals. Near-cap rows are highlighted.
 */
function AdminSpendSection() {
  const spend = useQuery(adminSpendApiAdminSpendGetOptions());
  return (
    <section
      aria-label="Spend"
      className="rounded-card border-line bg-panel mt-4 border p-5"
    >
      <h2 className="text-ink-faint font-display text-[11px] font-bold tracking-[0.28em] uppercase">
        Spend (all users)
      </h2>
      {spend.isPending && (
        <p className="text-ink-dim mt-3 text-sm">Loading spend…</p>
      )}
      {spend.isError && (
        <p className="text-ink-dim mt-3 text-sm">
          Could not load spend (are you signed in as an admin?).
        </p>
      )}
      {spend.isSuccess && (
        <>
          <p className="text-ink-dim mt-3 text-sm">
            Tenant month-to-date:{' '}
            <span className="text-ink font-medium">
              ${spend.data.total_month_to_date_usd.toFixed(2)}
            </span>
            <span className="text-ink-faint">
              {' '}
              · {spend.data.total_attempts_today} attempt
              {spend.data.total_attempts_today === 1 ? '' : 's'} today
            </span>
          </p>
          <ul className="mt-3 space-y-2 text-sm">
            {spend.data.users.map((user) => (
              <SpendRow key={user.id} user={user} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function SpendRow({ user }: { user: AdminUserSpend }) {
  const budget = user.budget_monthly_usd ?? null;
  const fraction =
    budget !== null && budget > 0 ? user.month_to_date_usd / budget : 0;
  const spendClass =
    fraction >= 1
      ? 'text-chili-bright'
      : fraction >= 0.8
        ? 'text-gold'
        : 'text-ink';
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <span className="text-ink flex items-center gap-2">
        {user.email}
        {user.paid_tier && (
          <span className="text-gold text-xs font-medium">paid</span>
        )}
      </span>
      <span className="flex items-baseline gap-2">
        <span className={`font-medium ${spendClass}`}>
          ${user.month_to_date_usd.toFixed(2)}
        </span>
        <span className="text-ink-faint text-xs">
          of {budget !== null ? `$${budget.toFixed(2)}` : 'no cap'}
          {user.cap_is_personal && ' (personal)'}
          {' · '}
          {user.attempts_today}
          {user.daily_attempt_cap !== null && `/${user.daily_attempt_cap}`}{' '}
          today
        </span>
      </span>
    </li>
  );
}

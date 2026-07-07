import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api-error';
import {
  adminSpendSummary,
  adminUserSpend,
  inviteOut,
  meOut,
  userAdminRow,
} from '../test/fixtures';
import { genState, resetGenState } from '../test/gen-mock';
import { renderApp } from '../test/render-app';

vi.mock('../client/@tanstack/react-query.gen', async () =>
  (await import('../test/gen-mock')).genMockModule(),
);

describe('AdminInvitesPage', () => {
  beforeEach(() => resetGenState());

  it('creates an invite and surfaces the dev activation link', async () => {
    genState.createInvite.mockResolvedValue(
      inviteOut({
        email: 'friend@example.com',
        dev_activation_link: 'http://localhost:8000/invite/tok',
      }),
    );
    renderApp('/admin/invites');
    fireEvent.change(await screen.findByLabelText('Invite an email'), {
      target: { value: 'friend@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send invite' }));

    await waitFor(() =>
      expect(genState.createInvite).toHaveBeenCalledWith(
        expect.objectContaining({ body: { email: 'friend@example.com' } }),
      ),
    );
    expect(
      await screen.findByText('http://localhost:8000/invite/tok'),
    ).toBeInTheDocument();
  });

  it('lists invites and revokes a pending one', async () => {
    genState.invitesList = [
      inviteOut({ id: 'inv1', email: 'a@x.com', status: 'pending' }),
    ];
    genState.revokeInvite.mockResolvedValue({ status: 'revoked' });
    renderApp('/admin/invites');

    expect(await screen.findByText('a@x.com')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Revoke' }));
    await waitFor(() =>
      expect(genState.revokeInvite).toHaveBeenCalledWith(
        expect.objectContaining({ path: { invite_id: 'inv1' } }),
      ),
    );
  });

  it('shows a friendly message when the email is already a member (409)', async () => {
    genState.createInvite.mockRejectedValue(
      new ApiError(409, 'Conflict', { detail: 'member' }),
    );
    renderApp('/admin/invites');
    fireEvent.change(await screen.findByLabelText('Invite an email'), {
      target: { value: 'member@x.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send invite' }));
    expect(await screen.findByText(/already a member/i)).toBeInTheDocument();
  });

  it('denies access for a non-admin (the server enforces it too)', async () => {
    genState.me = meOut({ is_admin: false });
    renderApp('/admin/invites');
    expect(await screen.findByText(/don't have access/i)).toBeInTheDocument();
  });

  it('shows the cross-user spend rollup with per-user caps and paid tier', async () => {
    renderApp('/admin/invites');

    const spend = within(await screen.findByRole('region', { name: 'Spend' }));
    // Tenant total.
    expect(await spend.findByText(/\$3\.50/)).toBeInTheDocument();
    // Per-user rows: the paid owner and the capped friend.
    expect(spend.getByText('owner@localhost')).toBeInTheDocument();
    expect(spend.getByText('friend@x.com')).toBeInTheDocument();
    expect(spend.getByText('$3.00')).toBeInTheDocument();
    // The friend's per-user cap is marked personal.
    expect(spend.getByText(/of \$2\.00 \(personal\)/)).toBeInTheDocument();
  });

  it('degrades gracefully when the spend rollup fails', async () => {
    genState.adminSpendError = new ApiError(503, 'Service Unavailable', {
      detail: 'db down',
    });
    renderApp('/admin/invites');
    const spend = within(await screen.findByRole('region', { name: 'Spend' }));
    expect(await spend.findByText(/could not load spend/i)).toBeInTheDocument();
  });

  it('lists members and toggles a real-frame cover grant', async () => {
    genState.usersList = [
      userAdminRow({ id: 'u1', email: 'owner@x.com', is_admin: true }),
      userAdminRow({
        id: 'u2',
        email: 'pal@x.com',
        real_covers_enabled: false,
      }),
    ];
    genState.setRealCovers.mockResolvedValue(
      userAdminRow({ id: 'u2', email: 'pal@x.com', real_covers_enabled: true }),
    );
    renderApp('/admin/invites');

    expect(await screen.findByText('pal@x.com')).toBeInTheDocument();
    // The owner row carries an "owner" marker.
    expect(screen.getByText('owner')).toBeInTheDocument();
    // Two grant checkboxes, both unchecked initially.
    const checkboxes = screen.getAllByRole('checkbox', {
      name: /real covers/i,
    });
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[1]).not.toBeChecked();

    fireEvent.click(checkboxes[1]); // grant pal@x.com
    await waitFor(() =>
      expect(genState.setRealCovers).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { user_id: 'u2' },
          body: { real_covers_enabled: true },
        }),
      ),
    );
  });

  it('surfaces an error when a grant update fails', async () => {
    genState.usersList = [userAdminRow({ id: 'u2', email: 'pal@x.com' })];
    genState.setRealCovers.mockRejectedValue(
      new ApiError(404, 'Not Found', { detail: 'no user' }),
    );
    renderApp('/admin/invites');

    fireEvent.click(
      await screen.findByRole('checkbox', { name: /real covers/i }),
    );
    expect(
      await screen.findByText(/could not update that grant/i),
    ).toBeInTheDocument();
  });

  // ── Budgets & tier (per-user caps + paid tier, M3) ──────────────────────────

  /** A single-user rollup so the Budgets controls are unambiguous to select. */
  function oneBudgetUser(over = {}) {
    genState.adminSpend = adminSpendSummary({
      users: [
        adminUserSpend({
          id: 'u9',
          email: 'pal@x.com',
          paid_tier: false,
          month_to_date_usd: 0.5,
          attempts_today: 1,
          budget_monthly_usd: 2,
          daily_attempt_cap: 5,
          cap_is_personal: true,
          ...over,
        }),
      ],
    });
  }

  it('shows each member with their effective cap + spend in Budgets & tier', async () => {
    oneBudgetUser();
    renderApp('/admin/invites');
    const budgets = within(
      await screen.findByRole('region', { name: 'Budgets & tier' }),
    );
    // The row carries spend context and its effective (personal) cap.
    expect(
      await budgets.findByText(/\$0\.50 spent of \$2\.00 \(personal\)/),
    ).toBeInTheDocument();
    // The number fields default to the effective caps as placeholders.
    expect(budgets.getByLabelText('Monthly budget ($)')).toHaveAttribute(
      'placeholder',
      '2.00',
    );
    expect(budgets.getByLabelText('Attempts / day')).toHaveAttribute(
      'placeholder',
      '5',
    );
  });

  it('saves a new monthly budget + daily cap for one member', async () => {
    oneBudgetUser();
    genState.updateUserBudget.mockResolvedValue(
      adminUserSpend({ id: 'u9', email: 'pal@x.com' }),
    );
    renderApp('/admin/invites');
    const form = await screen.findByRole('form', {
      name: 'Budget for pal@x.com',
    });
    const scoped = within(form);
    fireEvent.change(scoped.getByLabelText('Monthly budget ($)'), {
      target: { value: '12.5' },
    });
    fireEvent.change(scoped.getByLabelText('Attempts / day'), {
      target: { value: '8' },
    });
    fireEvent.click(scoped.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(genState.updateUserBudget).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { user_id: 'u9' },
          body: { monthly_budget_usd: 12.5, max_attempts_per_day: 8 },
        }),
      ),
    );
  });

  it('sends only the fields that were filled (partial update)', async () => {
    oneBudgetUser();
    genState.updateUserBudget.mockResolvedValue(
      adminUserSpend({ id: 'u9', email: 'pal@x.com' }),
    );
    renderApp('/admin/invites');
    const scoped = within(
      await screen.findByRole('form', { name: 'Budget for pal@x.com' }),
    );
    fireEvent.change(scoped.getByLabelText('Monthly budget ($)'), {
      target: { value: '9' },
    });
    fireEvent.click(scoped.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(genState.updateUserBudget).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { user_id: 'u9' },
          body: { monthly_budget_usd: 9 },
        }),
      ),
    );
  });

  it('rejects a non-positive cap without calling the API', async () => {
    oneBudgetUser();
    renderApp('/admin/invites');
    const scoped = within(
      await screen.findByRole('form', { name: 'Budget for pal@x.com' }),
    );
    fireEvent.change(scoped.getByLabelText('Monthly budget ($)'), {
      target: { value: '0' },
    });
    fireEvent.click(scoped.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByText(/must be a positive dollar amount/i),
    ).toBeInTheDocument();
    expect(genState.updateUserBudget).not.toHaveBeenCalled();
  });

  it('rejects an empty save (nothing to change)', async () => {
    oneBudgetUser();
    renderApp('/admin/invites');
    const scoped = within(
      await screen.findByRole('form', { name: 'Budget for pal@x.com' }),
    );
    fireEvent.click(scoped.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByText(/enter a new budget or cap/i),
    ).toBeInTheDocument();
    expect(genState.updateUserBudget).not.toHaveBeenCalled();
  });

  it('clears both caps to the global default via "Use global"', async () => {
    oneBudgetUser();
    genState.updateUserBudget.mockResolvedValue(
      adminUserSpend({ id: 'u9', email: 'pal@x.com' }),
    );
    renderApp('/admin/invites');
    const scoped = within(
      await screen.findByRole('form', { name: 'Budget for pal@x.com' }),
    );
    fireEvent.click(scoped.getByRole('button', { name: 'Use global' }));

    await waitFor(() =>
      expect(genState.updateUserBudget).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { user_id: 'u9' },
          body: { monthly_budget_usd: null, max_attempts_per_day: null },
        }),
      ),
    );
  });

  it('toggles a member onto the paid tier', async () => {
    oneBudgetUser({ paid_tier: false });
    genState.updateUserBudget.mockResolvedValue(
      adminUserSpend({ id: 'u9', email: 'pal@x.com', paid_tier: true }),
    );
    renderApp('/admin/invites');
    const budgets = within(
      await screen.findByRole('region', { name: 'Budgets & tier' }),
    );
    fireEvent.click(
      await budgets.findByRole('checkbox', { name: /paid model tier/i }),
    );

    await waitFor(() =>
      expect(genState.updateUserBudget).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { user_id: 'u9' },
          body: { paid_tier: true },
        }),
      ),
    );
  });

  it('surfaces an error when a budget update fails', async () => {
    oneBudgetUser();
    genState.updateUserBudget.mockRejectedValue(
      new ApiError(404, 'Not Found', { detail: 'no user' }),
    );
    renderApp('/admin/invites');
    const scoped = within(
      await screen.findByRole('form', { name: 'Budget for pal@x.com' }),
    );
    fireEvent.click(scoped.getByRole('button', { name: 'Use global' }));

    expect(
      await screen.findByText(/could not update that budget/i),
    ).toBeInTheDocument();
  });
});

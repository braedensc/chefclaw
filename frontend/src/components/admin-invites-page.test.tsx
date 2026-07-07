import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api-error';
import { inviteOut, meOut, userAdminRow } from '../test/fixtures';
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
});

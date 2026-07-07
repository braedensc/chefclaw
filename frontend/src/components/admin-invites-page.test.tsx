import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api-error';
import { inviteOut, meOut } from '../test/fixtures';
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
});

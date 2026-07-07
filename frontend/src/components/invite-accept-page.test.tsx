import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { invitePublic } from '../test/fixtures';
import { genState, resetGenState } from '../test/gen-mock';
import { renderApp } from '../test/render-app';

vi.mock('../client/@tanstack/react-query.gen', async () =>
  (await import('../test/gen-mock')).genMockModule(),
);

describe('InviteAcceptPage', () => {
  beforeEach(() => resetGenState());

  it('shows the invited email + Sign in for a live pending invite', async () => {
    genState.publicInviteResult = invitePublic({
      status: 'pending',
      email: 'friend@example.com',
    });
    renderApp('/invite/tok123');
    expect(await screen.findByText(/you're invited/i)).toBeInTheDocument();
    expect(screen.getByText('friend@example.com')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Sign in with Google' }),
    ).toBeInTheDocument();
  });

  it('shows an invalid notice (no email) for a non-pending token (M13)', async () => {
    genState.publicInviteResult = invitePublic({
      status: 'invalid',
      email: null,
    });
    renderApp('/invite/whatever');
    expect(await screen.findByText(/invite not valid/i)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Sign in with Google' }),
    ).not.toBeInTheDocument();
  });
});

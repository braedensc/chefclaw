import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api-error';
import { meOut } from '../test/fixtures';
import { genState, resetGenState } from '../test/gen-mock';
import { renderApp } from '../test/render-app';

vi.mock('../client/@tanstack/react-query.gen', async () =>
  (await import('../test/gen-mock')).genMockModule(),
);

describe('AuthGate + account menu', () => {
  beforeEach(() => resetGenState());

  it('shows the login page when /api/me is unauthenticated (401)', async () => {
    genState.meError = new ApiError(401, 'Unauthorized', {
      detail: 'no session',
    });
    renderApp('/');
    expect(
      await screen.findByRole('button', { name: 'Sign in with Google' }),
    ).toBeInTheDocument();
  });

  it('renders the app with a Sign out control when authenticated', async () => {
    renderApp('/');
    expect(
      await screen.findByRole('button', { name: 'Sign out' }),
    ).toBeInTheDocument();
  });

  it('shows the Admin nav for an admin', async () => {
    renderApp('/');
    expect(
      await screen.findByRole('link', { name: 'Admin' }),
    ).toBeInTheDocument();
  });

  it('hides the Admin nav for a non-admin (cosmetic gate)', async () => {
    genState.me = meOut({ is_admin: false });
    renderApp('/');
    expect(
      await screen.findByRole('button', { name: 'Sign out' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: 'Admin' }),
    ).not.toBeInTheDocument();
  });
});

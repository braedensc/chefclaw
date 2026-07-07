import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { resetGenState } from '../test/gen-mock';
import { renderApp } from '../test/render-app';

vi.mock('../client/@tanstack/react-query.gen', async () =>
  (await import('../test/gen-mock')).genMockModule(),
);

describe('LoginPage', () => {
  beforeEach(() => resetGenState());

  it('renders the Sign in with Google action on the public /login route', async () => {
    renderApp('/login');
    expect(
      await screen.findByRole('button', { name: 'Sign in with Google' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/invite-only/i)).toBeInTheDocument();
  });
});

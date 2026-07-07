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
    // No error param ⇒ no banner.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('surfaces a retryable banner when the callback bounced back ?error=expired', async () => {
    renderApp('/login?error=expired');
    expect(await screen.findByRole('alert')).toHaveTextContent(/link expired/i);
  });

  it('surfaces an opaque denied banner from ?error=denied', async () => {
    renderApp('/login?error=denied');
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /available for this account/i,
    );
  });
});

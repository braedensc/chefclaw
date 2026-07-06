import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TOKEN_STORAGE_KEY } from '../token';
import { useTokenActions } from '../token-context';
import { TokenGate } from './token-gate';

function ClearProbe() {
  const { clearToken } = useTokenActions();
  return (
    <button type="button" onClick={clearToken}>
      probe clear
    </button>
  );
}

describe('TokenGate', () => {
  it('renders the token prompt when no token is stored', () => {
    render(
      <TokenGate>
        <p>gated content</p>
      </TokenGate>,
    );

    expect(
      screen.getByText(
        'Paste your CHEFCLAW_API_TOKEN — stored only in this browser',
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('API token')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Save token' }),
    ).toBeInTheDocument();
    expect(screen.queryByText('gated content')).not.toBeInTheDocument();
  });

  it('renders its children when a token is already in localStorage', () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'placeholder-token');

    render(
      <TokenGate>
        <p>gated content</p>
      </TokenGate>,
    );

    expect(screen.getByText('gated content')).toBeInTheDocument();
    expect(
      screen.queryByText(
        'Paste your CHEFCLAW_API_TOKEN — stored only in this browser',
      ),
    ).not.toBeInTheDocument();
  });

  it('saves the entered token to localStorage and switches to children', () => {
    render(
      <TokenGate>
        <p>gated content</p>
      </TokenGate>,
    );

    fireEvent.change(screen.getByLabelText('API token'), {
      target: { value: 'placeholder-token' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save token' }));

    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('placeholder-token');
    expect(screen.getByText('gated content')).toBeInTheDocument();
  });

  it('clearToken from the context removes the token and re-gates', () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'placeholder-token');

    render(
      <TokenGate>
        <ClearProbe />
      </TokenGate>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'probe clear' }));

    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
    expect(screen.getByLabelText('API token')).toBeInTheDocument();
  });
});

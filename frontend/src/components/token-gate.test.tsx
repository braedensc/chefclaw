import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { HealthResponse } from '../client/types.gen';
import { TOKEN_STORAGE_KEY } from '../token';
import { TokenGate } from './token-gate';

// Mock the generated query-options module — component tests never real-fetch.
vi.mock('../client/@tanstack/react-query.gen', () => ({
  healthApiHealthGetOptions: () => ({
    queryKey: ['health-mock'],
    queryFn: async (): Promise<HealthResponse> => ({ status: 'ok', db: 'ok' }),
  }),
}));

function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe('TokenGate', () => {
  it('renders the token prompt when no token is stored', () => {
    renderWithQueryClient(<TokenGate />);

    expect(
      screen.getByText(
        'Paste your CHEFCLAW_API_TOKEN — stored only in this browser',
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('API token')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Save token' }),
    ).toBeInTheDocument();
  });

  it('renders the HealthPanel when a token is already in localStorage', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'placeholder-token');

    renderWithQueryClient(<TokenGate />);

    expect(
      await screen.findByRole('heading', { name: 'API health' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        'Paste your CHEFCLAW_API_TOKEN — stored only in this browser',
      ),
    ).not.toBeInTheDocument();
  });

  it('saves the entered token to localStorage and switches to the HealthPanel', async () => {
    renderWithQueryClient(<TokenGate />);

    fireEvent.change(screen.getByLabelText('API token'), {
      target: { value: 'placeholder-token' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save token' }));

    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('placeholder-token');
    expect(
      await screen.findByRole('heading', { name: 'API health' }),
    ).toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api-error';
import type { HealthResponse } from '../client/types.gen';
import { HealthPanel } from './health-panel';

// Mock the generated query-options module — component tests never real-fetch.
// The hoisted state lets each test choose success vs a specific failure. An
// ApiError simulates a non-2xx HTTP response (the api.ts interceptor wraps
// those); a plain Error simulates a network failure (no response at all).
const mockState = vi.hoisted(() => ({ failWith: null as Error | null }));

vi.mock('../client/@tanstack/react-query.gen', () => ({
  healthApiHealthGetOptions: () => ({
    queryKey: ['health-mock'],
    queryFn: async (): Promise<HealthResponse> => {
      if (mockState.failWith) throw mockState.failWith;
      return { status: 'ok', db: 'ok' };
    },
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

describe('HealthPanel', () => {
  it('renders the status and db fields reported by the API', async () => {
    mockState.failWith = null;

    renderWithQueryClient(<HealthPanel onClearToken={() => {}} />);

    expect(await screen.findByText('status')).toBeInTheDocument();
    expect(screen.getByText('db')).toBeInTheDocument();
    expect(screen.getAllByText('ok')).toHaveLength(2);
  });

  it('shows the token-rejected state with a prominent clear-token action on a 401', async () => {
    mockState.failWith = new ApiError(401, 'Unauthorized', {
      detail: 'Invalid token',
    });
    const onClearToken = vi.fn();

    renderWithQueryClient(<HealthPanel onClearToken={onClearToken} />);

    expect(
      await screen.findByText(/token rejected \(401\)/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/could not reach the api/i),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: 'Clear token & re-enter' }),
    );
    expect(onClearToken).toHaveBeenCalledTimes(1);
  });

  it('shows the unreachable state with a retry affordance on a network failure', async () => {
    mockState.failWith = new TypeError('Failed to fetch');
    const onClearToken = vi.fn();

    renderWithQueryClient(<HealthPanel onClearToken={onClearToken} />);

    expect(
      await screen.findByText(/could not reach the api/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/docker compose up/i)).toBeInTheDocument();
    expect(screen.queryByText(/401/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Clear token' }));
    expect(onClearToken).toHaveBeenCalledTimes(1);
  });

  it('shows a generic error including the status code on any other non-2xx', async () => {
    mockState.failWith = new ApiError(503, 'Service Unavailable', {
      detail: 'db down',
    });

    renderWithQueryClient(<HealthPanel onClearToken={() => {}} />);

    expect(await screen.findByText(/http 503/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});

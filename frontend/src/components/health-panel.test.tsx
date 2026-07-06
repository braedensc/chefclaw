import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { HealthResponse } from '../client/types.gen';
import { HealthPanel } from './health-panel';

// Mock the generated query-options module — component tests never real-fetch.
// The hoisted state lets each test choose success vs failure.
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

  it('shows a graceful error state with a clear-token affordance when the API is unreachable', async () => {
    mockState.failWith = new Error('network down');
    const onClearToken = vi.fn();

    renderWithQueryClient(<HealthPanel onClearToken={onClearToken} />);

    expect(
      await screen.findByText(/could not reach the api/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Clear token' }));
    expect(onClearToken).toHaveBeenCalledTimes(1);
  });
});

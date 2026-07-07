// Mounts the REAL route tree (router.tsx) on a memory history with a fresh
// QueryClient — component tests drive pages exactly as the app composes them.
// Callers must vi.mock the generated query-options module first (gen-mock.ts);
// nothing here performs real HTTP. The AuthGate resolves GET /api/me from the
// mock (genState.me — an authenticated admin by default), so gated pages render
// without any token seed (M2 cookie auth replaced the localStorage token).

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router';
import { render } from '@testing-library/react';

import { createAppRouter } from '../router';

export function renderApp(path = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createAppRouter(
    createMemoryHistory({ initialEntries: [path] }),
  );

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { ...utils, queryClient, router };
}

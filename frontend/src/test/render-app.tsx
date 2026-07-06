// Mounts the REAL route tree (router.tsx) on a memory history with a fresh
// QueryClient — component tests drive pages exactly as the app composes them.
// Callers must vi.mock the generated query-options module first (gen-mock.ts);
// nothing here performs real HTTP.

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router';
import { render } from '@testing-library/react';

import { createAppRouter } from '../router';
import { TOKEN_STORAGE_KEY } from '../token';

export function renderApp(path = '/') {
  // The TokenGate wraps every route; a stored (dummy, non-JWT) token opens it.
  localStorage.setItem(TOKEN_STORAGE_KEY, 'placeholder-token');

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

import {
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router';

import { TokenGate } from './components/token-gate';

function IndexPage() {
  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100">
      <TokenGate />
    </main>
  );
}

const rootRoute = createRootRoute();

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: IndexPage,
});

const routeTree = rootRoute.addChildren([indexRoute]);

export const router = createRouter({ routeTree });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}

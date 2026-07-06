import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from '@tanstack/react-router';
import type { RouterHistory } from '@tanstack/react-router';

import { AppShell } from './components/app-shell';
import { LibraryPage } from './components/library-page';
import { RecipeDetailPage } from './components/recipe-detail-page';
import { TokenGate } from './components/token-gate';

function RootLayout() {
  return (
    <TokenGate>
      <AppShell>
        <Outlet />
      </AppShell>
    </TokenGate>
  );
}

const rootRoute = createRootRoute({ component: RootLayout });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: LibraryPage,
});

const recipeDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/recipes/$id',
  component: RecipeDetailPage,
});

const routeTree = rootRoute.addChildren([indexRoute, recipeDetailRoute]);

/** Factory so tests can mount the real route tree on a memory history. */
export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history });
}

export const router = createAppRouter();

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}

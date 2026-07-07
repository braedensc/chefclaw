import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  useRouterState,
} from '@tanstack/react-router';
import type { RouterHistory } from '@tanstack/react-router';

import { AdminInvitesPage } from './components/admin-invites-page';
import { AppShell } from './components/app-shell';
import { AuthGate } from './components/auth-gate';
import { InviteAcceptPage } from './components/invite-accept-page';
import { LibraryPage } from './components/library-page';
import { LoginPage } from './components/login-page';
import { RecipeDetailPage } from './components/recipe-detail-page';
import { SettingsPage } from './components/settings-page';

/** /login and /invite/:token render OUTSIDE the auth gate; everything else is
 * gated on GET /api/me (M2 cookie session). */
function isPublicPath(pathname: string): boolean {
  return pathname === '/login' || pathname.startsWith('/invite/');
}

function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  if (isPublicPath(pathname)) {
    return <Outlet />;
  }
  return (
    <AuthGate>
      <AppShell>
        <Outlet />
      </AppShell>
    </AuthGate>
  );
}

const rootRoute = createRootRoute({ component: RootLayout });

// Public
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
});
const inviteRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/invite/$token',
  component: InviteAcceptPage,
});

// Gated (the RootLayout wraps these in AuthGate + AppShell)
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
const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage,
});
const adminInvitesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/admin/invites',
  component: AdminInvitesPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  inviteRoute,
  indexRoute,
  recipeDetailRoute,
  settingsRoute,
  adminInvitesRoute,
]);

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

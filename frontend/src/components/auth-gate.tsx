import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { ApiError } from '../api-error';
import { AuthContext } from '../auth-context';
import {
  logoutApiAuthLogoutPostMutation,
  meApiMeGetOptions,
  meApiMeGetQueryKey,
} from '../client/@tanstack/react-query.gen';
import { PuppyChef } from './brand/puppy-chef';
import { LoginPage } from './login-page';

/**
 * Gates every authenticated route on GET /api/me (the M2 cookie session). While
 * the identity resolves it shows a brief loading state; unauthenticated (401,
 * or any error — signing in is the only recovery) shows the LoginPage; on
 * success it provides the AuthContext (me + signOut) to its children.
 * Replaces the old localStorage TokenGate.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery(meApiMeGetOptions());
  const logout = useMutation({
    ...logoutApiAuthLogoutPostMutation(),
    // Whether or not the server call succeeds, drop the cached identity so the
    // gate re-queries and lands back on the login page.
    onSettled: () =>
      void queryClient.resetQueries({ queryKey: meApiMeGetQueryKey() }),
  });

  if (me.isPending) {
    return (
      <main className="text-ink flex min-h-screen items-center justify-center p-4">
        <PuppyChef
          variant="hero"
          animated
          size={120}
          className="opacity-70"
          label="Loading chefclaw"
        />
      </main>
    );
  }

  if (me.isError) {
    const status = me.error instanceof ApiError ? me.error.status : null;
    return <LoginPage sessionEnded={status === 401} />;
  }

  return (
    <AuthContext.Provider
      value={{ me: me.data, signOut: () => logout.mutate({}) }}
    >
      {children}
    </AuthContext.Provider>
  );
}

import { createContext, useContext } from 'react';

import type { MeOut } from './client/types.gen';

/**
 * The authenticated identity + session actions the AuthGate exposes to every
 * screen it wraps. `me.is_admin` gates admin-UI visibility ONLY — the server
 * enforces admin access at the transport layer (critique M9), so this is
 * cosmetic. Replaces the old token-clearing TokenContext.
 */
export interface AuthValue {
  me: MeOut;
  /** Sign out: kills the session server-side, then returns to the login gate. */
  signOut: () => void;
}

export const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error(
      'useAuth must be used inside an authenticated route (AuthGate)',
    );
  }
  return value;
}

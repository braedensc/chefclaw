import { createContext, useContext } from 'react';

/**
 * Actions the TokenGate exposes to everything it gates — currently just
 * clearing the stored token (the fix for a rejected/rotated token).
 */
export interface TokenActions {
  clearToken: () => void;
}

export const TokenContext = createContext<TokenActions>({
  clearToken: () => {},
});

export function useTokenActions(): TokenActions {
  return useContext(TokenContext);
}

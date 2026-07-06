// Single home for the SPA token flow: entered once in the UI, kept in
// localStorage, attached as a bearer header by src/api.ts. The token is a
// server secret at birth — it is NEVER a VITE_* build var (Hard Rule 4).
export const TOKEN_STORAGE_KEY = 'chefclaw_api_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function saveToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

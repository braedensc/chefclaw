import { QueryClient } from '@tanstack/react-query';

import { ApiError } from './api-error';
import { client } from './client/client.gen';

// Configure the generated client once, here. Base is same-origin: in dev the
// Vite proxy forwards /api to 127.0.0.1:8000; in prod the api container serves
// the SPA. Auth is the HttpOnly `chefclaw_session` cookie (M2) — the SPA never
// sees a token; `credentials: 'include'` sends the cookie on every request
// (same-origin, so it always would, but this is explicit and survives any
// future cross-origin dev setup).
client.setConfig({
  baseUrl: '',
  credentials: 'include',
});

// On a non-2xx response the generated client throws only the parsed error
// body — the status code is lost. Wrap it in ApiError here so the UI can
// branch on status (401 → sign in again vs anything else). A network failure
// never produces a response and passes through untouched, so `error instanceof
// ApiError` cleanly separates "the API answered with an error" from
// "unreachable".
client.interceptors.error.use((error, response) => {
  if (response && !response.ok) {
    return new ApiError(response.status, response.statusText, error);
  }
  return error;
});

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

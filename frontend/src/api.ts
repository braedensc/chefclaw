import { QueryClient } from '@tanstack/react-query';

import { client } from './client/client.gen';
import { getToken } from './token';

// Configure the generated client once, here. Base is same-origin: in dev the
// Vite proxy forwards /api to 127.0.0.1:8000; in prod the api container
// serves the SPA. Auth reads the bearer token from localStorage at request
// time (the generated SDK declares the HTTPBearer scheme, so the client adds
// the "Bearer " prefix). The token is never a build-time value (Hard Rule 4).
client.setConfig({
  baseUrl: '',
  auth: () => getToken() ?? undefined,
});

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

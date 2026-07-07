import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { queryClient } from './api';
import './index.css';
import { router } from './router';
import { maybeInitSentry } from './sentry';

// Before any render: a crash during mount should still be reported.
maybeInitSentry();

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element #root not found');
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);

// PWA (V2-C): register the service worker in PRODUCTION builds only — never
// during Vite dev/HMR, and never under an automated browser
// (`navigator.webdriver`, true in Playwright) so the smoke + golden suites stay
// deterministic. The SW uses a standard lifecycle (no skipWaiting/clients.claim,
// see public/sw.js), so it never controls the page that registered it;
// registration is best-effort — a failure must never break the app.
if (
  import.meta.env.PROD &&
  'serviceWorker' in navigator &&
  !navigator.webdriver
) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

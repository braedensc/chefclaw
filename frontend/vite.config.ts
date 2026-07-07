/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Dev proxies /api to the local FastAPI server so same-origin holds in dev;
// in prod the api container serves the SPA from the same origin. The target is
// overridable via CHEFCLAW_API_PROXY (e.g. point dev at the golden stack on
// :8100 for screenshots) — dev-only, never part of the prod bundle.
const API_PROXY_TARGET =
  process.env.CHEFCLAW_API_PROXY ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': API_PROXY_TARGET,
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});

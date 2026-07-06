import { fileURLToPath } from 'node:url';

import { defineConfig, devices } from '@playwright/test';

const e2eDir = fileURLToPath(new URL('.', import.meta.url));
const frontendRoot = fileURLToPath(new URL('..', import.meta.url));

// CI smoke contract (docs/TESTING.md): boots-and-renders with a dummy env —
// NO database, NO backend. The golden paste-to-card suite is LOCAL ONLY and
// lands in Phase 3; it does not live here.
export default defineConfig({
  testDir: e2eDir,
  // The DB-backed golden suite lives in e2e/golden with its OWN config
  // (playwright.golden.config.ts) — CI must structurally never run it.
  testIgnore: ['**/golden/**'],
  timeout: 30_000,
  fullyParallel: true,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command:
      'npm run build && npm run preview -- --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    cwd: frontendRoot,
    reuseExistingServer: false,
    timeout: 180_000,
  },
});

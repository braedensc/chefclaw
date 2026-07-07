import { fileURLToPath } from 'node:url';

import { defineConfig, devices } from '@playwright/test';

// LOCAL-ONLY golden paste-to-card suite (docs/TESTING.md; plan §16.9).
//
// A SEPARATE config file from the CI smoke on purpose: CI can structurally
// never pick this suite up. It drives the REAL golden compose stack
// (compose.golden.yaml — fake source + fake extractor, tmpfs Postgres,
// project `chefclaw-golden`), NEVER the daily-driver stack whose volumes are
// production data. There is deliberately NO webServer: the global setup
// fails fast with the bring-up command when the stack is not running.
//
//   docker compose -f compose.golden.yaml up -d --build
//   npm run test:golden            (from the repo root)
//   docker compose -f compose.golden.yaml down
//
// Serialized by contract: one shared stack + one canonical identity in the
// fake source ⇒ workers: 1, no parallelism, no retries (a retry would mask
// nondeterminism instead of fixing it).

const goldenDir = fileURLToPath(new URL('./golden', import.meta.url));

export const GOLDEN_BASE_URL = 'http://127.0.0.1:8100';

export default defineConfig({
  testDir: goldenDir,
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  globalSetup: fileURLToPath(
    new URL('./golden/global-setup.ts', import.meta.url),
  ),
  use: {
    baseURL: GOLDEN_BASE_URL,
    locale: 'en-US',
    timezoneId: 'UTC',
  },
  // Desktop + a phone viewport (Pixel 5 — touch, coarse pointer, isMobile) so
  // the same paste→card spec proves the V2-C responsive pass (bottom-sheet jobs
  // drawer, touch targets, mobile layout) end-to-end on both. Still workers: 1,
  // so the two projects run sequentially and the per-spec wipe keeps them
  // isolated. LOCAL-ONLY, like the whole golden suite — never runs in CI.
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 5'] } },
  ],
});

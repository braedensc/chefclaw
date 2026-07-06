import { GOLDEN_BASE_URL } from '../playwright.golden.config';

/**
 * Fail fast — with the exact bring-up command — when the golden stack is not
 * reachable. Any HTTP response (401 included: /api/health requires auth)
 * proves the api container is up; only a network-level failure rejects.
 */
export default async function globalSetup(): Promise<void> {
  try {
    await fetch(`${GOLDEN_BASE_URL}/api/health`);
  } catch {
    throw new Error(
      [
        `Golden stack is not reachable at ${GOLDEN_BASE_URL}.`,
        'This suite drives the isolated golden compose stack (never the',
        'daily-driver stack). Bring it up from the repo root with:',
        '',
        '  docker compose -f compose.golden.yaml up -d --build',
        '',
        'and take it down afterwards with:',
        '',
        '  docker compose -f compose.golden.yaml down',
      ].join('\n'),
    );
  }
}

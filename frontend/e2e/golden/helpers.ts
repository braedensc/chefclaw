import type { APIRequestContext } from '@playwright/test';

import { GOLDEN_BASE_URL } from '../playwright.golden.config';

// M2: the golden stack runs the api in FAKE auth mode (compose.golden.yaml has
// no CHEFCLAW_AUTH_PROVIDER, so it defaults to "fake"). require_owner then
// short-circuits to the seeded golden-owner (seed_golden_owner) with no cookie
// or token — GET /api/me resolves, the AuthGate passes, the app renders. So
// there is nothing to seed before a page loads (the old token seed is gone).

/**
 * Deterministic reset (docs/TESTING.md): hard-delete every stored recipe via
 * the API. DELETE re-opens extraction (the completed-job dedupe check only
 * matches while recipes exist — data-model ADR), so a re-paste after this
 * wipe always enqueues a FRESH job and the specs see the full status
 * progression even against a warm stack. No auth header needed — fake auth
 * authenticates every request as the golden owner.
 */
export async function wipeRecipes(request: APIRequestContext): Promise<void> {
  const listResponse = await request.get(
    `${GOLDEN_BASE_URL}/api/recipes?limit=200`,
  );
  if (!listResponse.ok()) {
    throw new Error(
      `golden wipe: GET /api/recipes failed (${listResponse.status()})`,
    );
  }
  const page = (await listResponse.json()) as { items: Array<{ id: string }> };
  for (const item of page.items) {
    const deleteResponse = await request.delete(
      `${GOLDEN_BASE_URL}/api/recipes/${item.id}`,
    );
    if (!deleteResponse.ok()) {
      throw new Error(
        `golden wipe: DELETE recipe ${item.id} failed (${deleteResponse.status()})`,
      );
    }
  }
}

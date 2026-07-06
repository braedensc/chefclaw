import type { APIRequestContext, Page } from '@playwright/test';

import { GOLDEN_BASE_URL } from '../playwright.golden.config';

/**
 * The golden stack's fixed bearer token (compose.golden.yaml) — a documented
 * TEST CONSTANT, not a secret. Key must match TOKEN_STORAGE_KEY in
 * src/token.ts (the SPA's single home for the token flow).
 */
export const GOLDEN_TOKEN = 'golden-test-token';
export const TOKEN_STORAGE_KEY = 'chefclaw_api_token';

const AUTH_HEADERS = { Authorization: `Bearer ${GOLDEN_TOKEN}` };

/** Seed the token before any page script runs, skipping the token prompt. */
export async function seedToken(page: Page): Promise<void> {
  await page.addInitScript(([key, token]) => localStorage.setItem(key, token), [
    TOKEN_STORAGE_KEY,
    GOLDEN_TOKEN,
  ] as const);
}

/**
 * Deterministic reset (docs/TESTING.md): hard-delete every stored recipe via
 * the API. DELETE re-opens extraction (the completed-job dedupe check only
 * matches while recipes exist — data-model ADR), so a re-paste after this
 * wipe always enqueues a FRESH job and the specs see the full status
 * progression even against a warm stack.
 */
export async function wipeRecipes(request: APIRequestContext): Promise<void> {
  const listResponse = await request.get(
    `${GOLDEN_BASE_URL}/api/recipes?limit=200`,
    { headers: AUTH_HEADERS },
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
      { headers: AUTH_HEADERS },
    );
    if (!deleteResponse.ok()) {
      throw new Error(
        `golden wipe: DELETE recipe ${item.id} failed (${deleteResponse.status()})`,
      );
    }
  }
}

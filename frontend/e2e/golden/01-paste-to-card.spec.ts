import { expect, test } from '@playwright/test';

import { STAGES } from '../../src/lib/cooking-stages';
import { seedToken, wipeRecipes } from './helpers';

// The core-loop golden path (plan §16.9): paste → job chip → stored card →
// detail. The fake source resolves EVERY fake:// URL to ONE canonical
// identity (fake-golden-1); the beforeEach wipe (hard delete re-opens
// extraction) guarantees this spec drives a FRESH job — full status
// progression — even against a warm stack. Specs are number-prefixed to run
// in a fixed order under workers: 1.
//
// Selector contract (restyles must keep these; docs/TESTING.md "semantic
// selectors survive restyles"):
//   textbox  "Video link"            — the paste bar input
//   button   "Extract"               — the paste bar submit
//   status   (role)                  — a live job chip; text carries the url
//   link     /dish name/             — a library card
//   button   "原文"                  — ingredients toggle, aria-pressed state
//   button   "Show raw JSON"         — extraction-metadata drawer
//   region   "Raw extraction JSON"   — the opened drawer

const PASTE_URL = 'fake://golden-e2e-1';
const DISH_EN = 'Red-braised pork belly';

// Active-stage chip copy comes from the SAME map the chip renders
// (src/lib/cooking-stages.ts) — spec and UI copy stay in lockstep.
const ACTIVE_STAGE_COPY = new RegExp(
  Object.values(STAGES)
    .filter((stage) => stage.step !== null)
    .map((stage) => stage.copy.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|'),
);

test.beforeEach(async ({ request }) => {
  await wipeRecipes(request);
});

test('paste a link, watch the chip to stored, browse the card and detail', async ({
  page,
}) => {
  await seedToken(page);
  await page.goto('/');

  // Paste bar pinned at the top of the library.
  await page.getByRole('textbox', { name: 'Video link' }).fill(PASTE_URL);
  await page.getByRole('button', { name: 'Extract' }).click();

  // The job chip appears inline with a live (non-terminal) status — the
  // worker's politeness jitter guarantees a visible active window. Chips
  // speak the cooking-stage vocabulary (src/lib/cooking-stages.ts, V2-E);
  // the jobs DRAWER keeps the sober statusLabel words (spec 02 asserts
  // "Stored" there).
  const chip = page.getByRole('status').filter({ hasText: PASTE_URL });
  await expect(chip).toBeVisible();
  await expect(chip).toContainText(ACTIVE_STAGE_COPY);

  // On stored the chip morphs into the card: card in the grid, chip gone.
  const card = page.getByRole('link', { name: new RegExp(DISH_EN) });
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(chip).toHaveCount(0);
  await expect(card).toContainText('红烧肉');
  await expect(card).toContainText('bilibili');

  // Click through to the detail page.
  await card.click();
  await expect(
    page.getByRole('heading', { name: new RegExp(DISH_EN) }),
  ).toBeVisible();

  // 原文 toggle: EN names by default, verbatim raw_text when toggled.
  const toggle = page.getByRole('button', { name: '原文' });
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByText('pork belly', { exact: true })).toBeVisible();
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('五花肉500克')).toBeVisible();

  // Raw-JSON drawer: pretty-printed document + extraction_meta.
  await page.getByRole('button', { name: 'Show raw JSON' }).click();
  const rawJson = page.getByRole('region', { name: 'Raw extraction JSON' });
  await expect(rawJson).toBeVisible();
  await expect(rawJson).toContainText('"dish_name"');
  await expect(rawJson).toContainText('"extraction_meta"');
});

import { expect, test } from '@playwright/test';

// The jobs drawer lists the extraction job as stored. Runs after
// 01-paste-to-card (workers: 1, filename-ordered); pasting again is a
// canonical dedupe hit that returns the SAME job, so this spec is also
// self-sufficient if run alone against a fresh stack. Earlier runs leave
// older jobs behind (spec 01's wipe re-opens extraction), so the assertion
// targets the NEWEST matching row — the drawer sorts by latest activity.
//
// Selector contract (restyles must keep these):
//   button        "Jobs"       — header toggle for the drawer
//   complementary "Jobs"       — the drawer itself (an aria-labelled <aside>)
//   listitem      (role)       — one job row: platform badge, canonical id,
//                                status label

test('the jobs drawer lists the extraction job as stored', async ({ page }) => {
  await page.goto('/');

  // Ensure the job exists (fresh stack) or dedupe-hit the existing one.
  await page
    .getByRole('textbox', { name: 'Video link' })
    .fill('fake://golden-e2e-1');
  await page.getByRole('button', { name: 'Extract' }).click();

  await page.getByRole('button', { name: 'Jobs' }).click();
  const drawer = page.getByRole('complementary', { name: 'Jobs' });
  await expect(drawer).toBeVisible();

  const row = drawer
    .getByRole('listitem')
    .filter({ hasText: 'fake-golden-1' })
    .first();
  await expect(row).toBeVisible();
  await expect(row).toContainText('bilibili');
  // The drawer polls; the row reaches the terminal stored state.
  await expect(row).toContainText('Stored', { timeout: 30_000 });
});

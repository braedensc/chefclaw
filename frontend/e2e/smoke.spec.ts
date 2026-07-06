import { expect, test } from '@playwright/test';

// Boots-and-renders smoke: fresh browser context has no token in
// localStorage, so the app must render the token prompt. No backend runs.
test('app boots and renders the token prompt', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByText(
      'Paste your CHEFCLAW_API_TOKEN — stored only in this browser',
    ),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save token' })).toBeVisible();
});

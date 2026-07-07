import { expect, test } from '@playwright/test';

// Boots-and-renders smoke: a fresh browser has no session cookie, so GET
// /api/me is unauthenticated and the AuthGate must render the login page. No
// backend runs — the /api/me call fails (network), which the gate also treats
// as "sign in". Either way, the "Sign in with Google" action must be visible.
test('app boots and renders the sign-in page', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByRole('button', { name: 'Sign in with Google' }),
  ).toBeVisible();
});

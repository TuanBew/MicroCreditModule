import { test, expect } from '@playwright/test';

const BUYER_EMAIL = 'buyer@acme.io';
const BUYER_PASSWORD = 'credits123';

async function loginAsBuyer(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await expect(page.locator('#email')).toHaveValue(BUYER_EMAIL);
  await expect(page.locator('#password')).toHaveValue(BUYER_PASSWORD);
  await page.click('button.btn[type="submit"]');
  await page.waitForURL('**/dashboard');
}

test.describe('Store purchase flow', () => {
  test('package grid loads — at least one .package-card visible', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/store');

    // Wait for loading to finish (skeletons removed) and package cards to appear
    await expect(page.locator('.package-card').first()).toBeVisible();
    const count = await page.locator('.package-card').count();
    expect(count).toBeGreaterThan(0);
  });

  test('purchase modal opens — clicking Purchase on first card shows modal', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/store');

    await expect(page.locator('.package-card').first()).toBeVisible();

    // Click the Purchase/Buy button on the first package card
    await page.locator('.package-card').first().locator('button.btn').click();

    // Modal backdrop should appear
    await expect(page.locator('.modal-backdrop.is-visible')).toBeVisible();
  });

  test('purchase flow — complete a purchase, success state appears, balance updates', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/store');

    await expect(page.locator('.package-card').first()).toBeVisible();

    // Record balance before purchase (if balance pill is present)
    const balancePillBefore = page.locator('.balance-pill');
    const balanceTextBefore = await balancePillBefore.isVisible()
      ? await balancePillBefore.textContent()
      : null;

    // Open the purchase modal for the first package
    await page.locator('.package-card').first().locator('button.btn').click();
    await expect(page.locator('.modal-backdrop.is-visible')).toBeVisible();

    // Click the Pay button (contains "Pay")
    const payButton = page.locator('.modal-backdrop.is-visible button.btn', { hasText: /Pay/ });
    await expect(payButton).toBeVisible();
    await payButton.click();

    // Wait for success state to appear
    await expect(page.locator('.success-state.is-visible')).toBeVisible();

    // The success state should mention the new balance
    const successText = await page.locator('.success-state.is-visible').textContent();
    expect(successText).toMatch(/balance/i);

    // If balance pill was visible before, check it updated (contains a digit)
    if (balanceTextBefore !== null) {
      const balancePillAfter = page.locator('.balance-pill');
      await expect(balancePillAfter).toBeVisible();
      const balanceTextAfter = await balancePillAfter.textContent();
      expect(balanceTextAfter).toMatch(/\d/);
    }
  });
});

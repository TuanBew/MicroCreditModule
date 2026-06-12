import { test, expect } from '@playwright/test';
import { loginAsBuyer } from './helpers';

test.describe('Store, wallet & playground — Docker stack', () => {
  test('buyer sees 32 credits on dashboard', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/dashboard');

    const balanceNumber = page.locator('.balance-number');
    await expect(balanceNumber).toBeVisible();
    await expect(balanceNumber.locator('.spinner')).toHaveCount(0);

    const text = await balanceNumber.textContent();
    expect(text).toContain('32');
  });

  test('store page shows at least one package', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/store');

    await expect(page.locator('.package-card').first()).toBeVisible();
    const count = await page.locator('.package-card').count();
    expect(count).toBeGreaterThan(0);
  });

  test('buyer can open a checkout modal', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/store');

    await expect(page.locator('.package-card').first()).toBeVisible();
    await page.locator('.package-card').first().locator('button.btn').click();
    await expect(page.locator('.modal-backdrop.is-visible')).toBeVisible();
  });

  test('playground page loads and shows feature panels', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/playground');

    await expect(page.locator('.feature-panel').first()).toBeVisible();
    const count = await page.locator('.feature-panel').count();
    expect(count).toBe(4);
  });
});

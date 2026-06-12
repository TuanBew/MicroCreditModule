import { test, expect } from '@playwright/test';
import { loginAsBuyer, loginAsAdmin } from './helpers';

test.describe('Auth routing — Docker stack', () => {
  test('unauthenticated user visiting /store is redirected to /login', async ({ page }) => {
    await page.goto('/store');
    await page.waitForURL('**/login');
    await expect(page).toHaveURL(/\/login/);
  });

  test('buyer can log in and lands on dashboard', async ({ page }) => {
    await loginAsBuyer(page);
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.locator('.balance-pill')).toBeVisible();
  });

  test('buyer visiting /admin/packages is redirected away', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/admin');
    await page.waitForURL(/\/(login|dashboard)/);
    await expect(page).not.toHaveURL(/\/admin/);
  });

  test('admin can log in and lands on admin page', async ({ page }) => {
    await loginAsAdmin(page);
    await expect(page).toHaveURL(/\/admin/);
    await expect(page.locator('h1')).toContainText('Manage credit packages');
  });
});

import { test, expect } from '@playwright/test';

const BUYER_EMAIL = 'buyer@acme.io';
const BUYER_PASSWORD = 'credits123';
const ADMIN_EMAIL = 'admin@creditos.app';
const ADMIN_PASSWORD = 'credits123';

test.describe('Authentication', () => {
  test('login buyer — pre-filled credentials redirect to /dashboard with balance pill', async ({ page }) => {
    await page.goto('/login');

    // Verify pre-filled buyer credentials
    await expect(page.locator('#email')).toHaveValue(BUYER_EMAIL);
    await expect(page.locator('#password')).toHaveValue(BUYER_PASSWORD);

    await page.click('button.btn[type="submit"]');

    await page.waitForURL('**/dashboard');
    await expect(page).toHaveURL(/\/dashboard/);

    // Balance pill should be visible for buyer role
    await expect(page.locator('.balance-pill')).toBeVisible();
  });

  test('login admin — click "Use admin demo", submit, redirect to /admin', async ({ page }) => {
    await page.goto('/login');

    await page.click('button.btn-secondary:has-text("Use admin demo")');

    // Verify admin credentials were filled
    await expect(page.locator('#email')).toHaveValue(ADMIN_EMAIL);
    await expect(page.locator('#password')).toHaveValue(ADMIN_PASSWORD);

    await page.click('button.btn[type="submit"]');

    await page.waitForURL('**/admin');
    await expect(page).toHaveURL(/\/admin/);
  });

  test('redirect unauthenticated — navigate to /dashboard redirects to /login', async ({ page }) => {
    await page.goto('/dashboard');

    await page.waitForURL('**/login');
    await expect(page).toHaveURL(/\/login/);
  });

  test('logout — login as buyer, click logout, redirect to /login', async ({ page }) => {
    await page.goto('/login');
    await expect(page.locator('#email')).toHaveValue(BUYER_EMAIL);
    await expect(page.locator('#password')).toHaveValue(BUYER_PASSWORD);
    await page.click('button.btn[type="submit"]');
    await page.waitForURL('**/dashboard');

    await page.click('button.logout-link');

    await page.waitForURL('**/login');
    await expect(page).toHaveURL(/\/login/);
  });
});

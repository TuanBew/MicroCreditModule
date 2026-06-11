import { test, expect } from '@playwright/test';

const BUYER_EMAIL = 'buyer@acme.io';
const BUYER_PASSWORD = 'credits123';
const ADMIN_EMAIL = 'admin@creditos.app';
const ADMIN_PASSWORD = 'credits123';

async function loginAsBuyer(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await expect(page.locator('#email')).toHaveValue(BUYER_EMAIL);
  await expect(page.locator('#password')).toHaveValue(BUYER_PASSWORD);
  await page.click('button.btn[type="submit"]');
  await page.waitForURL('**/dashboard');
}

async function loginAsAdmin(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await page.click('button.btn-secondary:has-text("Use admin demo")');
  await expect(page.locator('#email')).toHaveValue(ADMIN_EMAIL);
  await expect(page.locator('#password')).toHaveValue(ADMIN_PASSWORD);
  await page.click('button.btn[type="submit"]');
  await page.waitForURL('**/admin');
}

test.describe('Admin access control', () => {
  test('buyer cannot access admin — redirect away from /admin', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/admin');

    // ProtectedRoute redirects buyer away from /admin to /dashboard
    await page.waitForURL(/\/(login|dashboard)/);
    await expect(page).not.toHaveURL(/\/admin/);
  });

  test('admin can access admin page — h1 contains "Manage credit packages"', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/admin');
    await expect(page).toHaveURL(/\/admin/);

    const heading = page.locator('h1');
    await expect(heading).toBeVisible();
    // The actual h1 text from Admin.tsx: "Manage credit packages without touching customer usage history."
    await expect(heading).toContainText('Manage credit packages');
  });

  test('create package — as admin, click New package, fill form, save, assert new package in table', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/admin');

    // Click "New package" button
    const newPackageBtn = page.locator('button.btn', { hasText: 'New package' });
    await expect(newPackageBtn).toBeVisible();
    await newPackageBtn.click();

    // Modal should open
    await expect(page.locator('.modal-backdrop.is-visible')).toBeVisible();

    // Fill in the package form
    const packageName = `Test Package ${Date.now()}`;
    await page.fill('#pkg-name', packageName);
    await page.fill('#pkg-description', 'Automated test package');
    await page.fill('#pkg-price', '1999');
    await page.fill('#pkg-credits', '500');

    // Select at least one feature via checkbox
    const featureCheckboxes = page.locator('.checkbox-list input[type="checkbox"]');
    const checkboxCount = await featureCheckboxes.count();
    if (checkboxCount > 0) {
      await featureCheckboxes.first().check();
    }

    // Submit the form
    const saveBtn = page.locator('button.btn[type="submit"]', { hasText: /Save package/ });
    await saveBtn.click();

    // Modal should close and table should update
    await expect(page.locator('.modal-backdrop.is-visible')).not.toBeVisible();

    // New package should appear in the table
    await expect(page.locator('td', { hasText: packageName })).toBeVisible();
  });
});

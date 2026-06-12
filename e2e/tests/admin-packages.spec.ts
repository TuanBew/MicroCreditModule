import { test, expect } from '@playwright/test';
import { loginAsAdmin, loginAsBuyer } from './helpers';

test.describe('Admin packages — Docker stack', () => {
  test('admin can log in and see the packages table', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/admin');

    await expect(page.locator('h1')).toContainText('Manage credit packages');
    // At least one row in the packages table
    await expect(page.locator('table')).toBeVisible();
    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible();
  });

  test('admin can open the New Package modal', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/admin');

    const newPackageBtn = page.locator('button.btn', { hasText: 'New package' });
    await expect(newPackageBtn).toBeVisible();
    await newPackageBtn.click();

    await expect(page.locator('.modal-backdrop.is-visible')).toBeVisible();
  });

  test('buyer cannot access admin page — redirected', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/admin');

    await page.waitForURL(/\/(login|dashboard)/);
    await expect(page).not.toHaveURL(/\/admin/);
  });
});

import { expect, type Page } from '@playwright/test';

const BUYER_EMAIL = 'buyer@acme.io';
const BUYER_PASSWORD = 'credits123';
const ADMIN_EMAIL = 'admin@creditos.app';
const ADMIN_PASSWORD = 'credits123';

export async function loginAsBuyer(page: Page) {
  await page.goto('/login');
  await expect(page.locator('#email')).toHaveValue(BUYER_EMAIL);
  await expect(page.locator('#password')).toHaveValue(BUYER_PASSWORD);
  await page.click('button.btn[type="submit"]');
  await page.waitForURL('**/dashboard');
}

export async function loginAsAdmin(page: Page) {
  await page.goto('/login');
  await page.click('button.btn-secondary:has-text("Use admin demo")');
  await expect(page.locator('#email')).toHaveValue(ADMIN_EMAIL);
  await expect(page.locator('#password')).toHaveValue(ADMIN_PASSWORD);
  await page.click('button.btn[type="submit"]');
  await page.waitForURL('**/admin');
}

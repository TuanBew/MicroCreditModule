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

test.describe('Dashboard', () => {
  test('balance visible — .balance-number shows a number after loading', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/dashboard');

    const balanceNumber = page.locator('.balance-number');
    await expect(balanceNumber).toBeVisible();

    // Wait until the spinner is gone (balance loaded)
    await expect(balanceNumber.locator('.spinner')).toHaveCount(0);

    // Balance text should contain at least one digit
    const text = await balanceNumber.textContent();
    expect(text).toMatch(/\d/);
  });

  test('history tabs — both tabs exist; clicking "Credit activity" makes it active', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/dashboard');

    const purchaseTab = page.locator('.tab', { hasText: 'Purchase history' });
    const creditTab = page.locator('.tab', { hasText: 'Credit activity' });

    await expect(purchaseTab).toBeVisible();
    await expect(creditTab).toBeVisible();

    await creditTab.click();

    // After clicking, the credit activity tab should be active
    await expect(creditTab).toHaveClass(/is-active/);
    // Purchase history tab should no longer be active
    await expect(purchaseTab).not.toHaveClass(/is-active/);
  });
});

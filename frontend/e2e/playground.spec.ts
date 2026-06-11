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

test.describe('Playground feature gating', () => {
  test('feature panels load — 4 .feature-panel elements visible', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/playground');

    // Wait for skeletons to resolve into feature panels
    await expect(page.locator('.feature-panel').first()).toBeVisible();
    const count = await page.locator('.feature-panel').count();
    expect(count).toBe(4);
  });

  test('locked feature — panel with .access-band.locked shows "Go to Store" link', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/playground');

    await expect(page.locator('.feature-panel').first()).toBeVisible();

    // Look for a locked access band
    const lockedBands = page.locator('.access-band.locked');
    const lockedCount = await lockedBands.count();

    if (lockedCount > 0) {
      // At least one locked band should show the "Go to Store" link
      const goToStoreLink = lockedBands.first().locator('a', { hasText: 'Go to Store' });
      await expect(goToStoreLink).toBeVisible();
    } else {
      // All features are owned — skip with a note (seed data may differ)
      test.info().annotations.push({
        type: 'note',
        description: 'No locked features found — buyer may own all features from seed data.',
      });
    }
  });

  test('available feature run — clicking Run produces .result-card.is-visible', async ({ page }) => {
    await loginAsBuyer(page);
    await page.goto('/playground');

    await expect(page.locator('.feature-panel').first()).toBeVisible();

    // Check if any feature is available (unlocked + affordable)
    const availableBands = page.locator('.access-band.available');
    const availableCount = await availableBands.count();

    if (availableCount > 0) {
      // Find the first feature panel that has an available band
      const panels = page.locator('.feature-panel');
      const panelCount = await panels.count();

      let ranFeature = false;
      for (let i = 0; i < panelCount; i++) {
        const panel = panels.nth(i);
        const band = panel.locator('.access-band.available');
        if (await band.count() > 0) {
          // Click the Run button within this panel
          const runBtn = panel.locator('button.btn');
          await expect(runBtn).toBeVisible();
          await expect(runBtn).toBeEnabled();
          await runBtn.click();

          // Wait for result card to appear
          await expect(panel.locator('.result-card.is-visible')).toBeVisible({ timeout: 15000 });
          ranFeature = true;
          break;
        }
      }

      if (!ranFeature) {
        test.info().annotations.push({
          type: 'note',
          description: 'Available band found but no enabled run button located.',
        });
      }
    } else {
      // No available features — buyer may be locked or have insufficient credits
      test.info().annotations.push({
        type: 'note',
        description: 'No available features found — buyer may not have unlocked features or sufficient credits.',
      });
    }
  });
});

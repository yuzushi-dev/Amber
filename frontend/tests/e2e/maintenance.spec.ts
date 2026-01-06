import { test, expect } from '@playwright/test';

test.describe('Maintenance Page', () => {
    test('should load maintenance page', async ({ page }) => {
        // Navigate to the Maintenance page (canonical URL)
        await page.goto('/admin/data/maintenance');

        // Check if Maintenance header is visible
        // Adjust locator based on actual page content, likely a heading
        await expect(page.getByRole('heading', { name: /maintenance|database/i })).toBeVisible();

        // Check for presence of key elements like "System Status" or "Clear Cache"
        // This is a smoke test, so generic visibility of main container is enough
        await expect(page.locator('main')).toBeVisible();
    });
});

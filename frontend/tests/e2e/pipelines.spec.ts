import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

test.describe('Amber 2.0 Pipelines E2E Tests', () => {

    test('Ingestion Pipeline: Document Upload', async ({ page }) => {
        // 1. Navigate to the Documents page
        await page.goto('/admin/data/documents');

        // Create a dummy file to upload with unique content
        const timestamp = Date.now();
        const testFileName = `e2e-test-${timestamp}.txt`;
        const testFileContent = `This is a test document for Amber 2.0 ingestion. Timestamp: ${timestamp}`;
        const filePath = path.resolve('tests/e2e', testFileName);
        fs.writeFileSync(filePath, testFileContent);

        try {
            // 2. Click "Upload Knowledge" button (accessible name comes from aria-label)
            await page.getByRole('button', { name: 'Upload new document' }).click();

            // 3. Handle file input in the wizard
            const fileInput = page.locator('#file-upload');
            await fileInput.setInputFiles(filePath);

            // 4. Click "Start Ingestion"
            await page.getByRole('button', { name: 'Start Ingestion' }).click();

            // 5. Wait for the success message in the wizard
            await expect(page.getByText('Knowledge successfully integrated!')).toBeVisible({ timeout: 10000 });

            // 6. Navigate back or wait for modal to close (UploadWizard closes after 1.5s)
            await expect(page.locator('text=Knowledge successfully integrated!')).not.toBeVisible({ timeout: 10000 });

            // 7. Verify file appears in the Document Library list
            // Document processing is async, so we need to poll
            const fileBaseName = testFileName.replace('.txt', '');
            const regex = new RegExp(fileBaseName);

            // Poll for up to 30 seconds (processing can take time)
            for (let i = 0; i < 6; i++) {
                await page.reload();
                await page.waitForTimeout(5000);

                const docTitles = await page.locator('.font-medium').allInnerTexts();
                console.log(`Poll ${i + 1}: Found documents:`, docTitles);

                const found = docTitles.some(title => regex.test(title));
                if (found) {
                    console.log(`Document ${testFileName} found after ${(i + 1) * 5} seconds`);
                    break;
                }
            }

            await expect(page.getByText(regex)).toBeVisible({ timeout: 5000 });



        } finally {
            // Cleanup
            if (fs.existsSync(filePath)) {
                fs.unlinkSync(filePath);
            }
        }
    });

    test('Search/Chat Pipeline: Query and Response', async ({ page }) => {
        // 1. Navigate to the Chat page
        await page.goto('/amber/chat');

        // 2. Identify the chat input using the ID found in QueryInput.tsx
        const chatInput = page.locator('#query-input');
        await expect(chatInput).toBeVisible({ timeout: 15000 });

        // 3. Type a query
        const query = 'Hello, e2e test query';
        await chatInput.fill(query);

        // 4. Send using the button (or Enter)
        await page.getByLabel('Send query').click();

        // 5. Verify the user message appears
        await expect(page.getByText(query)).toBeVisible();

        // 6. Verify the AI response appears
        // We look for the "Amber Assistant" label which indicates a bot response
        await expect(page.getByText('Amber Assistant')).toBeVisible({ timeout: 30000 });

        // Optional: Verify content is non-empty
        // We can look for the Markdown container
        const messages = page.locator('.prose'); // MessageItem.tsx uses "prose" class
        // Wait for content to arrive (streaming might take a moment)
        // Message content might be empty if still thinking.
        // Verify we have either content OR a thinking indicator.
        const thinking = page.locator('.animate-spin'); // Loader2 has animate-spin
        const hasContent = await messages.last().innerText();

        if (!hasContent) {
            await expect(thinking).toBeVisible();
        } else {
            await expect(messages.last()).not.toBeEmpty();
        }
    });
});

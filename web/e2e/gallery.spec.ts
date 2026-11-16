// /gallery draws every group's sections without errors. The screenshots are in screenshots.spec.ts.

import { expect, test, type ConsoleMessage } from '@playwright/test';
import { SHEET_SECTIONS } from '../src/pages/gallery/sheet.ts';

test('every section draws, with no errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(`page error: ${error.message}`));
  page.on('console', (message: ConsoleMessage) => {
    // Missing covers are drawn on purpose (the mock 404s them), and the browser logs each 404.
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource')) {
      errors.push(`console error: ${message.text()}`);
    }
  });

  await page.goto('/gallery');
  await expect(page.getByRole('heading', { name: 'Component gallery', level: 1 })).toBeVisible();
  const sections = page.locator('[data-gallery-section]');
  await expect(sections.first()).toBeVisible();

  // An entry that throws shows its error in place (EntryBoundary): name each one.
  const broken = await page.locator('[data-gallery-error]').evaluateAll((nodes) => nodes.map((n) => n.textContent));
  expect(broken, 'entries that failed to draw').toEqual([]);
  expect(errors, 'errors while drawing the gallery').toEqual([]);
});

test('the sections follow the sheet, and the contents link each one', async ({ page }) => {
  await page.goto('/gallery');
  const sections = page.locator('[data-gallery-section]');
  const titles = await sections.locator('h2').allTextContents();
  const nodes = await sections.evaluateAll((all) => all.map((s) => s.getAttribute('data-sheet-node')));

  // Sections on the sheet come first, in its order, with its node ids.
  const onSheet = nodes.filter((n): n is string => !!n);
  const sheetOrder = SHEET_SECTIONS.map((s) => s.node).filter((n) => onSheet.includes(n));
  expect(onSheet).toEqual(sheetOrder);
  expect(nodes.slice(0, onSheet.length)).toEqual(onSheet);

  const contents = page.getByRole('navigation', { name: 'Gallery' });
  for (const title of titles) {
    await expect(contents.getByRole('link', { name: title, exact: true })).toBeVisible();
  }
  await contents.getByRole('link', { name: 'Shell, live' }).click();
  await expect(page).toHaveURL(/\/gallery\?view=shell$/);
  await expect(page.getByRole('heading', { name: 'Shell, live' })).toBeVisible();
});

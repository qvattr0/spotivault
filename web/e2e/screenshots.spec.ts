// Screenshots at 2x, to set beside the S3 reference PNGs (web/design-reference/, also 2x):
// - each gallery section as E3ZmN.<section node>.png, at the sheet's width (2400);
// - each S8 page in the state of its drawn frame (e2e/page-screens.ts) as <frame node>.png, 1440
//   wide and as tall as the frame (960, or the frame's own height).
// They go to e2e/screenshots/ (gitignored), and the run ends by writing the side-by-side report,
// e2e/screenshots/index.html (e2e/report.ts). Nothing here compares pixels: the report is for eyes.

import { expect, test } from '@playwright/test';
import { SCREEN_SIZE } from '../src/pages/gallery/screens.ts';
import { SHEET_NODE, SHEET_SIZE } from '../src/pages/gallery/sheet.ts';
import { openPage, useScenario } from './mock.ts';
import { PAGE_SCREENS } from './page-screens.ts';
import { removeScreenshots, screenshotPath, writeReport } from './report.ts';

test.use({ deviceScaleFactor: 2 });

test.afterAll(() => {
  writeReport();
});

test.describe('gallery sections', () => {
  test.use({ viewport: { width: SHEET_SIZE.width, height: 1200 } });

  test("each section, at the sheet's width", async ({ page }) => {
    await page.goto('/gallery');
    const sections = page.locator('[data-gallery-section]');
    await expect(sections.first()).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    // Sections come and go as the groups grow: start from none.
    removeScreenshots(`${SHEET_NODE}.`, 'gallery.');

    for (const section of await sections.all()) {
      const node = await section.getAttribute('data-sheet-node');
      const id = await section.getAttribute('data-gallery-section');
      // A section the sheet doesn't have keeps its own name, and the report says it has no drawing.
      const name = node ? `${SHEET_NODE}.${node}.png` : `gallery.${id}.png`;
      await test.step(name, async () => {
        await section.screenshot({ path: screenshotPath(name), animations: 'disabled' });
      });
    }
  });
});

test.describe('page screens', () => {
  // Some wait for a run to reach the drawn moment (an album recording).
  test.setTimeout(60_000);

  for (const screen of PAGE_SCREENS) {
    test(`${screen.node}: ${screen.title}`, async ({ page, request }) => {
      // A frame taller than 960 is drawn whole: the window gets its height, so nothing scrolls.
      await page.setViewportSize({ width: SCREEN_SIZE.width, height: screen.height ?? SCREEN_SIZE.height });
      await useScenario(request, screen.scenario, screen.step ? { step: screen.step } : {});
      await openPage(page, screen.path);
      await expect(page).toHaveURL(new RegExp(`${screen.path}$`));
      await screen.prepare?.(page, request);
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: screenshotPath(`${screen.node}.png`), animations: 'disabled' });
    });
  }
});

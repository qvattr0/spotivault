// The foundation: the setup gate, the gallery's fonts and the favicon. The live run state is in
// shell.spec.ts, the gallery in gallery.spec.ts and screenshots.spec.ts.

import { expect, test } from '@playwright/test';
import { openPage, useScenario } from './mock.ts';

test('before setup, every route goes to the wizard', async ({ page, request }) => {
  await useScenario(request, 'setup');
  await page.goto('/library');
  await expect(page).toHaveURL(/\/setup\/client-settings$/);
  const steps = page.getByRole('list', { name: 'Setup steps' });
  await expect(steps.getByRole('listitem').nth(3)).toHaveAttribute('aria-current', 'step');
});

test('the setup scenario can start at any step', async ({ page, request }) => {
  await useScenario(request, 'setup', { step: 'webapi' });
  await page.goto('/library');
  await expect(page).toHaveURL(/\/setup\/web-api$/);
  await useScenario(request, 'setup', { step: 'output' });
  // Step 6 is the first unfinished one only while /music isn't mounted (as in the controller).
  await page.goto('/setup');
  await expect(page).toHaveURL(/\/setup\/output$/);
});

test('every app page opens after setup, titled as its sidebar entry', async ({ page, request }) => {
  await useScenario(request, 'idle');
  for (const [path, title] of [
    ['/dashboard', 'Dashboard'],
    ['/library', 'Library'],
    ['/albums', 'Albums'],
    ['/history/runs', 'History'],
    ['/settings', 'Settings'],
    ['/player', 'Player'],
  ]) {
    await openPage(page, path);
    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible();
  }
  await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Schedule' })).toHaveCount(0);
});

test('the gallery opens, with the tokens and the self-hosted fonts', async ({ page, request }) => {
  await useScenario(request, 'fresh');
  await page.goto('/gallery');
  await expect(page.getByRole('heading', { name: 'Component gallery' })).toBeVisible();
  await expect(page.getByText('Display 40/800')).toBeVisible();
  const figtree = await page.evaluate(async () => {
    await document.fonts.ready;
    return document.fonts.check('800 40px Figtree');
  });
  expect(figtree).toBe(true);
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe('rgb(0, 0, 0)');

  // The favicon is the brand's logo-32.svg.
  const icon = await page.evaluate(async () => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    const response = link ? await fetch(link.href) : null;
    // Small SVGs are inlined as data: URLs, with single quotes.
    return { status: response?.status, svg: /aria-label=["']spotivault["']/.test((await response?.text()) ?? '') };
  });
  expect(icon).toEqual({ status: 200, svg: true });
});

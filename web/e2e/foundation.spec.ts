// The foundation: the setup gate, the gallery's fonts and the favicon. The live run state is in
// shell.spec.ts, the gallery in gallery.spec.ts and screenshots.spec.ts.

import { expect, test } from '@playwright/test';
import { useScenario } from './mock.ts';

test('before setup, every route goes to the wizard', async ({ page, request }) => {
  await useScenario(request, 'setup');
  await page.goto('/library');
  await expect(page).toHaveURL(/\/setup\/client-settings$/);
  await expect(page.getByRole('heading', { name: '4. Client settings' })).toBeVisible();
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

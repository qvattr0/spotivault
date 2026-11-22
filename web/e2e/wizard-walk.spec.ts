// The whole wizard against the mock, from a new container to the Library: the main path, step by
// step, with each step's Continue.

import { expect, test } from '@playwright/test';
import { openPage, useScenario } from './mock.ts';

test('a new container walks through the nine steps to the Library', async ({ page, request }) => {
  test.setTimeout(90_000);
  await useScenario(request, 'fresh');
  await page.context().route('https://accounts.spotify.com/**', (route) => route.fulfill({ contentType: 'text/html', body: '<p>Consent</p>' }));
  await openPage(page, '/');
  const proceed = page.getByRole('button', { name: 'Continue' });
  const steps = page.getByRole('list', { name: 'Setup steps' });

  // 1. Welcome
  await expect(page).toHaveURL(/\/setup\/welcome$/);
  await page.getByLabel('I understand').check();
  await proceed.click();

  // 2. Spotify client: the mock waits for Install (the controller starts it by itself).
  await expect(page).toHaveURL(/\/setup\/client$/);
  await page.getByRole('button', { name: 'Install' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'The Spotify client is installed' })).toBeVisible({ timeout: 20_000 });
  await proceed.click();

  // 3. Log in: the mock logs in a few seconds after the install.
  await expect(page).toHaveURL(/\/setup\/login$/);
  await expect(page.getByText('Logged in. This step is done.')).toBeVisible({ timeout: 15_000 });
  await proceed.click();

  // 4. Client settings: the mock's settings turn tidy 5 s after the login (as fake mode's do);
  // Re-check reads them again.
  await expect(page).toHaveURL(/\/setup\/client-settings$/);
  await expect(async () => {
    if (await proceed.isDisabled()) await page.getByRole('button', { name: 'Re-check' }).click();
    await expect(proceed).toBeEnabled({ timeout: 1_000 });
  }).toPass({ timeout: 20_000 });
  await proceed.click();

  // 5. Web API
  await expect(page).toHaveURL(/\/setup\/web-api$/);
  await page.getByLabel('Client ID').fill('0123456789abcdef0123456789abcdef');
  const popup = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Open Spotify consent page' }).click();
  const tab = await popup;
  await tab.waitForURL(/accounts\.spotify\.com/);
  const state = new URL(tab.url()).searchParams.get('state');
  await tab.close();
  await page.getByLabel('Address of the error page').fill(`http://127.0.0.1:8888/callback?code=AQB3x&state=${state}`);
  await page.getByRole('button', { name: 'Connect' }).click();
  await expect(proceed).toBeEnabled();
  await proceed.click();

  // 6. Output: /music is fine in a new container.
  await expect(page).toHaveURL(/\/setup\/output$/);
  await expect(page.getByText('/music is mounted and writable')).toBeVisible();
  await proceed.click();

  // 7. What to back up, 8. Albums: the defaults.
  await expect(page).toHaveURL(/\/setup\/playlists$/);
  await proceed.click();
  await expect(page).toHaveURL(/\/setup\/albums$/);
  await proceed.click();

  // 9. Done
  await expect(page).toHaveURL(/\/setup\/done$/);
  await expect(steps.getByRole('listitem')).toHaveCount(9);
  for (const label of ['Welcome', 'Spotify client', 'Log in', 'Client settings', 'Web API', 'Output', 'Playlists', 'Albums']) {
    await expect(steps.getByRole('link', { name: new RegExp(`^${label}\\b.*done$`) })).toBeVisible();
  }
  await page.getByRole('button', { name: 'Open Library' }).click();
  await expect(page).toHaveURL(/\/library$/);
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
});

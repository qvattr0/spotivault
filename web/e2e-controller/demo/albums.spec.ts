// The Albums pages against the real controller in fake mode, `demo` project: the + modal adds a
// saved album, the album's detail view records it (Record now), and the grid shows it recording
// with a link to the Dashboard. The demo's controller is shared, so each test puts back the album
// it added and stops the run it started.

import { expect, test, type APIRequestContext } from '@playwright/test';
import type { Album, SavedAlbum } from '../../src/api/types.ts';
import { demoReady, getJson, openPage, stopAnyRun, waitForRunState } from '../helpers.ts';

test.beforeAll(async ({ request }) => {
  await demoReady(request);
});

test.afterEach(async ({ request }) => {
  await stopAnyRun(request);
});

/** Adds the first saved album through the API, and returns it (the tests remove it again). */
async function addFirstSavedAlbum(request: APIRequestContext): Promise<SavedAlbum> {
  const saved = await getJson<{ items: SavedAlbum[] }>(request, '/api/albums/saved');
  const album = saved.items[0];
  expect(album, 'the demo has saved albums').toBeTruthy();
  const response = await request.post('/api/albums', { data: { ids: [album!.id] } });
  expect(response.ok()).toBe(true);
  return album!;
}

/** Puts an album back: the page drops it, and it's a saved album again. */
async function removeAlbum(request: APIRequestContext, id: string): Promise<void> {
  await request.delete(`/api/albums/${id}`);
}

test('the + modal adds a saved album, and the page shows it as Queued', async ({ page, request }) => {
  const before = await getJson<{ items: Album[] }>(request, '/api/albums');
  const saved = await getJson<{ items: SavedAlbum[] }>(request, '/api/albums/saved');
  const target = saved.items[0]!;
  try {
    await openPage(page, '/albums');
    await page.getByRole('button', { name: 'Add albums' }).click();
    const modal = page.getByRole('dialog', { name: 'Add albums' });
    await expect(modal.getByText(target.name, { exact: true })).toBeVisible();
    await modal.getByRole('button', { name: `Add ${target.name}`, exact: true }).click();
    await expect(modal.getByText(target.name, { exact: true })).toHaveCount(0);
    await modal.getByRole('button', { name: 'Done' }).click();

    await expect(page.getByRole('button', { name: target.name, exact: true })).toBeVisible();
    const after = await getJson<{ items: Album[] }>(request, '/api/albums');
    expect(after.items.length).toBe(before.items.length + 1);
    expect(after.items.find((a) => a.id === target.id)?.status).toBe('queued');
  } finally {
    await removeAlbum(request, target.id);
  }
});

test('Record now records the album: the grid shows it Recording, linking to the Dashboard', async ({ page, request }) => {
  const target = await addFirstSavedAlbum(request);
  try {
    await openPage(page, `/albums/${target.id}`);
    await expect(page.getByRole('heading', { level: 1, name: target.name })).toBeVisible();
    await page.getByRole('button', { name: 'Record now' }).click();
    await waitForRunState(request, 'running');

    await openPage(page, '/albums');
    const recording = page.getByRole('link', { name: 'Recording' });
    await expect(recording.first()).toBeVisible({ timeout: 60_000 });
    await expect(recording.first()).toHaveAttribute('href', '/dashboard');
  } finally {
    await stopAnyRun(request);
    await removeAlbum(request, target.id);
  }
});

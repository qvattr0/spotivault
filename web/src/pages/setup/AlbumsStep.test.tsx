// Wizard step 8 (web-ui.md § 8): each answer goes to the controller, then Continue opens step 9.
// "I'll choose in Albums" queues nothing, but it's still an answer: it marks the step done
// (POST /api/setup/albums/later), so the stepper ticks Albums and a reload resumes at step 9.
// Coming back to the done step shows the answer given, so Continue doesn't turn it into the other.

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { savedAlbums, setupAt } from '@mock/fixtures.ts';
import { api, type SavedAlbum } from '@/api';
import { ToastProvider, ToastViewport } from '@/components/ui-b';
import { createLiveStore, LiveStoreProvider } from '@/state';
import { envelope } from '@/test/live.ts';
import { AlbumsStep } from './AlbumsStep.tsx';

const ok = (data: unknown) => Promise.resolve({ data, response: new Response(null, { status: 200 }) });

/** Every POST the step sends: its path and its body. */
let posts: { path: string; body: unknown }[];
/** Set to make POST /api/setup/albums/later get no answer, as with the controller down. */
let laterFails: boolean;
/** GET /api/albums/saved's `items`: the saved albums not on the Albums page. Null: no answer. */
let offThePage: SavedAlbum[] | null;

beforeEach(() => {
  posts = [];
  laterFails = false;
  offThePage = [];
  // The typed client keeps the fetch it was made with, so its methods are stubbed.
  vi.spyOn(api, 'GET').mockImplementation((() =>
    offThePage === null ? Promise.reject(new TypeError('fetch failed')) : ok({ saved_total: 42, items: offThePage })) as never);
  vi.spyOn(api, 'POST').mockImplementation(((path: string, init?: { body?: unknown }) => {
    posts.push({ path, body: init?.body });
    if (path === '/api/setup/albums/later') {
      return laterFails ? Promise.reject(new TypeError('fetch failed')) : ok(setupAt('done'));
    }
    return ok({ added: [], skipped: [] });
  }) as never);
});

afterEach(() => vi.restoreAllMocks());

/** Opens step 8 with the setup state at `active`: 'albums' the first time, 'done' once answered. */
function renderStep(active: 'albums' | 'done' = 'albums') {
  const store = createLiveStore();
  store.dispatch(envelope('setup.state', setupAt(active)));
  render(
    <MemoryRouter initialEntries={['/setup/albums']}>
      <LiveStoreProvider store={store}>
        <ToastProvider>
          <Routes>
            <Route path="/setup/albums" element={<AlbumsStep />} />
            <Route path="/setup/done" element={<h1>Step 9</h1>} />
          </Routes>
          <ToastViewport />
        </ToastProvider>
      </LiveStoreProvider>
    </MemoryRouter>,
  );
}

const all = () => screen.getByRole('radio', { name: 'Back up all my saved albums' });
const later = () => screen.getByRole('radio', { name: "I'll choose in Albums" });

describe('step 8: Albums', () => {
  it('"Back up all my saved albums" (picked at first) adds them all, then opens step 9', async () => {
    const user = userEvent.setup();
    renderStep();
    expect(await screen.findByText('You have 42 saved albums')).toBeInTheDocument();
    expect(all()).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByRole('heading', { name: 'Step 9' })).toBeInTheDocument();
    expect(posts).toEqual([{ path: '/api/albums', body: { all: true } }]);
  });

  it('"I\'ll choose in Albums" answers the step without adding albums, then opens step 9', async () => {
    const user = userEvent.setup();
    renderStep();
    await user.click(later());
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByRole('heading', { name: 'Step 9' })).toBeInTheDocument();
    expect(posts).toEqual([{ path: '/api/setup/albums/later', body: undefined }]);
  });

  it('"I\'ll choose in Albums" that fails: a toast says why, and the step stays', async () => {
    laterFails = true;
    const user = userEvent.setup();
    renderStep();
    await user.click(later());
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByText("Can't reach spotivault. Check that it's running, then try again.")).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Which albums should spotivault back up?' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Step 9' })).not.toBeInTheDocument();
    expect(posts.map((p) => p.path)).toEqual(['/api/setup/albums/later']);
  });
});

describe('step 8, coming back once it is done', () => {
  it('after "I\'ll choose in Albums" (saved albums still off the page): it\'s picked, and Continue adds nothing', async () => {
    offThePage = savedAlbums;
    const user = userEvent.setup();
    renderStep('done');
    expect(await screen.findByText('You have 42 saved albums')).toBeInTheDocument();
    expect(later()).toBeChecked();
    expect(all()).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByRole('heading', { name: 'Step 9' })).toBeInTheDocument();
    expect(posts).toEqual([{ path: '/api/setup/albums/later', body: undefined }]);
  });

  it('after "Back up all my saved albums" (none left off the page): it\'s picked', async () => {
    renderStep('done');
    expect(await screen.findByText('You have 42 saved albums')).toBeInTheDocument();
    expect(all()).toBeChecked();
  });

  it('while the saved albums can\'t be read: "I\'ll choose in Albums", the answer that adds nothing', async () => {
    offThePage = null;
    const user = userEvent.setup();
    renderStep('done');
    expect(later()).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByRole('heading', { name: 'Step 9' })).toBeInTheDocument();
    expect(posts.map((p) => p.path)).toEqual(['/api/setup/albums/later']);
  });

  it('your own choice still wins', async () => {
    offThePage = savedAlbums;
    const user = userEvent.setup();
    renderStep('done');
    expect(await screen.findByText('You have 42 saved albums')).toBeInTheDocument();
    await user.click(all());
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByRole('heading', { name: 'Step 9' })).toBeInTheDocument();
    expect(posts).toEqual([{ path: '/api/albums', body: { all: true } }]);
  });
});

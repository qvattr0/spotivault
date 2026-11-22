// The Full backup card (web-ui.md § Idle, card 2) in each state. The live store gives one estimate
// (the hello's, then `backlog` events) and GET /api/backlog another: the newer one, by as_of, shows.

import { act, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { backlog as sample, backlogComplete, backlogFresh, backlogMeasuring, helloFor } from '@mock/fixtures.ts';
import { api, type Backlog } from '@/api';
import { createLiveStore, LiveStoreProvider, type LiveStore } from '@/state';
import { envelope } from '@/test/live.ts';
import { FullBackupCard } from './FullBackupCard.tsx';

const ok = (data: unknown) => Promise.resolve({ data, response: new Response(null, { status: 200 }) });

/** GET /api/backlog answers `read` (null: no answer, as with the controller down). Returns the stub. */
function answer(read: Backlog | null) {
  return vi
    .spyOn(api, 'GET')
    .mockImplementation((() => (read ? ok(read) : Promise.reject(new TypeError('fetch failed')))) as never);
}

afterEach(() => vi.restoreAllMocks());

/** A store whose hello carries `live` as its backlog. */
function storeWith(live: Backlog | null): LiveStore {
  const store = createLiveStore();
  store.dispatch(envelope('hello', { ...helloFor('idle'), backlog: live }));
  return store;
}

function renderCard(store: LiveStore) {
  render(
    <MemoryRouter>
      <LiveStoreProvider store={store}>
        <FullBackupCard />
      </LiveStoreProvider>
    </MemoryRouter>,
  );
  return screen.getByRole('region', { name: 'Full backup' });
}

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

describe('FullBackupCard', () => {
  it('in progress with a schedule: the bar, the tracks, the time left and the finish date', async () => {
    const live = { ...sample, finish_at: '2026-11-21T12:00:00Z', as_of: minutesAgo(5) };
    answer(live);
    const card = renderCard(storeWith(live));
    // 90.9 % of the time: the bar says the same rounded-down 90 as the line under it.
    const bar = within(card).getByRole('progressbar', { name: 'Full backup' });
    expect(bar).toHaveAttribute('aria-valuenow', '90');
    expect(within(card).getByText('4,708 of 5,120 tracks · 90% of the music')).toBeInTheDocument();
    expect(within(card).getByText('About 27 h of recording left')).toBeInTheDocument();
    expect(within(card).getByText('Done around Sat 21 Nov at this schedule')).toBeInTheDocument();
    expect(within(card).getByText('+ 2 followed playlists (unknown length)')).toBeInTheDocument();
    // The day is added only when as_of wasn't today (just after midnight here).
    expect(within(card).getByText(/^Updated (\w{3} \d+ \w{3} )?\d\d:\d\d$/)).toBeInTheDocument();
    expect(card).not.toHaveAttribute('aria-busy');
  });

  it('nearly done: neither the bar nor the line says 100 before the last track', async () => {
    const live = { ...sample, tracks_recorded: 5119, seconds_recorded: 1_072_799, seconds_left: 36, as_of: minutesAgo(5) };
    answer(live);
    const card = renderCard(storeWith(live));
    expect(within(card).getByRole('progressbar', { name: 'Full backup' })).toHaveAttribute('aria-valuenow', '99');
    expect(within(card).getByText('5,119 of 5,120 tracks · 99% of the music')).toBeInTheDocument();
    expect(within(card).getByText('About 1 min of recording left')).toBeInTheDocument();
  });

  it('in progress with Manual only: Run now to start, and nothing unknown', async () => {
    const live = { ...backlogFresh, unknown_items: 0, as_of: minutesAgo(5) };
    answer(live);
    const card = renderCard(storeWith(live));
    expect(within(card).getByText('0 of 5,120 tracks · 0% of the music')).toBeInTheDocument();
    expect(within(card).getByText('About 298 h of recording left')).toBeInTheDocument();
    expect(within(card).getByText('Run now to start; recording is real time')).toBeInTheDocument();
    expect(within(card).queryByText(/unknown length/)).not.toBeInTheDocument();
  });

  it('some lists still being measured: the figures so far, and how many are left to measure', async () => {
    const live = { ...sample, items_measuring: 1, as_of: minutesAgo(5) };
    answer(live);
    const card = renderCard(storeWith(live));
    expect(within(card).getByText('About 27 h of recording left')).toBeInTheDocument();
    expect(within(card).getByText('+ 1 playlist or album still being measured')).toBeInTheDocument();
  });

  it('Complete: a check and Everything is backed up, with no bar', async () => {
    const live = { ...backlogComplete, as_of: minutesAgo(5) };
    answer(live);
    const card = renderCard(storeWith(live));
    expect(within(card).getByText('Everything is backed up · 298 h of music')).toBeInTheDocument();
    expect(within(card).queryByRole('progressbar')).not.toBeInTheDocument();
    expect(within(card).getByText(/^Updated /)).toBeInTheDocument();
  });

  it('everything of known length recorded, some unknown: not "Everything is backed up"', async () => {
    const live = { ...backlogComplete, unknown_items: 2, as_of: minutesAgo(5) };
    answer(live);
    const card = renderCard(storeWith(live));
    expect(within(card).getByText('Everything of known length is backed up · 298 h of music')).toBeInTheDocument();
    expect(within(card).getByText('+ 2 followed playlists (unknown length)')).toBeInTheDocument();
    expect(within(card).queryByText(/^Everything is backed up/)).not.toBeInTheDocument();
    expect(within(card).queryByRole('progressbar')).not.toBeInTheDocument();
    expect(within(card).queryByText(/at this schedule|Run now to start/)).not.toBeInTheDocument();
  });

  it('Measuring: a busy skeleton, and its text for screen readers', async () => {
    const live = { ...backlogMeasuring, as_of: minutesAgo(5) };
    answer(live);
    const card = renderCard(storeWith(live));
    const text = within(card).getByText('Measuring your library…');
    expect(text).toBeVisible();
    expect(text.closest('[aria-busy="true"]')).not.toBeNull();
    expect(text.closest('[aria-hidden="true"]')).toBeNull();
    expect(within(card).queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('Measuring before any estimate, then the GET answer replaces it', async () => {
    answer({ ...sample, as_of: minutesAgo(1) });
    const card = renderCard(storeWith(null));
    expect(within(card).getByText('Measuring your library…')).toBeInTheDocument();
    expect(await within(card).findByText('About 27 h of recording left')).toBeInTheDocument();
  });

  it('the newer estimate wins: a backlog event after the GET answer', async () => {
    const read = { ...sample, as_of: minutesAgo(10) };
    answer(read);
    const store = storeWith({ ...sample, as_of: minutesAgo(20) });
    const card = renderCard(store);
    expect(await within(card).findByText('About 27 h of recording left')).toBeInTheDocument();
    act(() => store.dispatch(envelope('backlog', { ...backlogComplete, as_of: minutesAgo(0) })));
    expect(within(card).getByText('Everything is backed up · 298 h of music')).toBeInTheDocument();
  });

  it('reads the estimate again when a catalog refresh ends, not when one starts', async () => {
    // The controller sends `backlog` only when a figure changed: this read moves "Updated" on.
    const before = { ...sample, as_of: '2026-11-21T01:00:00Z' };
    const get = answer(before);
    const store = storeWith(before);
    const card = renderCard(store);
    expect(await within(card).findByText('About 27 h of recording left')).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(1);
    const refresh = { refresh_id: 57, trigger: 'page_open', reason: null } as const;
    const counts = { outcome: null, items_changed: null, items_added: null, suggestions_added: null };
    act(() => store.dispatch(envelope('catalog.refresh', { ...refresh, ...counts, state: 'started' })));
    expect(get).toHaveBeenCalledTimes(1);
    const after = { ...sample, as_of: minutesAgo(0) };
    get.mockImplementation((() => ok(after)) as never);
    const ended = { ...refresh, state: 'ended', outcome: 'ok', items_changed: 0, items_added: 0, suggestions_added: 0 } as const;
    act(() => store.dispatch(envelope('catalog.refresh', ended)));
    await vi.waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(await within(card).findByText(/^Updated \d\d:\d\d$/)).toBeInTheDocument();
  });

  it('the newer estimate wins: a GET answer newer than the hello', async () => {
    answer({ ...backlogComplete, as_of: minutesAgo(1) });
    const card = renderCard(storeWith({ ...sample, as_of: minutesAgo(30) }));
    expect(await within(card).findByText('Everything is backed up · 298 h of music')).toBeInTheDocument();
  });

  it('only playlists of unknown length: says how many, with no bar', async () => {
    const unknownOnly = { ...backlogMeasuring, unknown_items: 1, items_measuring: 0, as_of: minutesAgo(5) };
    answer(unknownOnly);
    const card = renderCard(storeWith(unknownOnly));
    expect(within(card).getByText('1 followed playlist (unknown length)')).toBeInTheDocument();
    expect(within(card).queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('nothing tracked: points to the Library and Albums', async () => {
    const zero = { ...backlogMeasuring, unknown_items: 0, items_measuring: 0, as_of: minutesAgo(5) };
    answer(zero);
    const card = renderCard(storeWith(zero));
    expect(within(card).getByText('Nothing to back up yet')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'Open Library' })).toHaveAttribute('href', '/library');
    expect(within(card).getByRole('link', { name: 'Open Albums' })).toHaveAttribute('href', '/albums');
  });

  it('no estimate and the read failed: says why instead of measuring', async () => {
    answer(null);
    const card = renderCard(storeWith(null));
    expect(await within(card).findByText(/reach spotivault|went wrong|Try again/i)).toBeInTheDocument();
    expect(within(card).queryByText('Measuring your library…')).not.toBeInTheDocument();
  });
});

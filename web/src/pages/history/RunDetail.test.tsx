// The page of a run still going (web-ui.md § Run page): it follows the run. The controller builds
// the queue after the pre-run check (run.queue; a run that starts paused sends no item.state then),
// and an open item's track list grows as takes end. The REST answers are stubbed here and changed
// between events, as the controller's would.

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { queueItem, runRunning } from '@mock/fixtures.ts';
import { api, type HistoryRow, type RunItem, type TrackResult } from '@/api';
import { ToastProvider } from '@/components/ui-b';
import { LiveStoreProvider, type LiveStore } from '@/state';
import { envelope, storeFor } from '@/test/live.ts';
import { RunDetail } from './RunDetail.tsx';

const RUN_ID = runRunning.id;

const liveRow: HistoryRow = {
  id: RUN_ID, kind: 'run', trigger: 'scheduled', started_at: runRunning.started_at, ended_at: null, duration_s: null,
  outcome: null, counters: runRunning.counters, reason: null, window: null,
};

const liked: RunItem = {
  item_id: 'liked', kind: 'liked', name: 'Liked Songs', cover: null, order: 1, state: 'playing', badges: [],
  counts: { recorded: 0, skipped: 0, failed: 0 }, bytes: 0, started_at: runRunning.started_at, ended_at: null, reason: null,
  can_retry: false,
};

function take(title: string): TrackResult {
  return {
    position: 1, track_id: `id-${title}`, title, artists: ['fakename'], result: 'recorded', reason: null, size_bytes: 3_400_000,
    path: `fakename/Liked Songs/${title}.m4a`, take_id: title, at: '2026-11-15T00:01:00Z',
  };
}

/** What the stubbed controller answers now: the run page's items, and Liked Songs' track results. */
let answers: { run: HistoryRow; items: RunItem[]; tracks: TrackResult[] };

beforeEach(() => {
  answers = { run: liveRow, items: [], tracks: [] };
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    const data = path === '/api/runs/{id}' ? { run: answers.run, items: answers.items } : { tracks: answers.tracks };
    return Promise.resolve({ data, response: new Response(null, { status: 200 }) });
  }) as never);
});

afterEach(() => vi.restoreAllMocks());

function renderPage(): LiveStore {
  // The store's run is this one (the mock's "running" hello).
  const store = storeFor('running');
  render(
    <MemoryRouter>
      <LiveStoreProvider store={store}>
        <ToastProvider>
          <RunDetail runId={RUN_ID} />
        </ToastProvider>
      </LiveStoreProvider>
    </MemoryRouter>,
  );
  return store;
}

describe('the page of a run still going', () => {
  it('shows the items once the queue is built, even when no item.state follows (a run that starts paused)', async () => {
    const store = renderPage();
    expect(await screen.findByText('Building the queue…')).toBeInTheDocument();

    answers.items = [{ ...liked, state: 'up_next', started_at: null }];
    store.dispatch(envelope('run.queue', { run_id: RUN_ID, queue: [queueItem({ item_id: 'liked', kind: 'liked', name: 'Liked Songs' })] }));
    expect(await screen.findByRole('button', { name: 'Liked Songs' })).toBeInTheDocument();
    expect(screen.queryByText('Building the queue…')).not.toBeInTheDocument();
  });

  it("keeps an open item's tracks current as takes end, and after the run ends", async () => {
    answers.items = [liked];
    const store = renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Liked Songs' }));
    expect(await screen.findByText('No tracks in this run.')).toBeInTheDocument();

    // A take ends: the list grows.
    answers.tracks = [take('Last Hours')];
    store.dispatch(
      envelope('track.finished', {
        run_id: RUN_ID, item_id: 'liked', take_id: 'Last Hours', track_id: 'id-Last Hours', path: 'x', duration_ms: 6000,
        bytes: 3_400_000, counted: true, low_volume: false, pause_fade: false, partial: false,
      }),
    );
    const table = await screen.findByRole('table', { name: 'Tracks of Liked Songs' });
    expect(within(table).getByText('Last Hours')).toBeInTheDocument();

    // The run ends (run.state idle, then run.finished): the list is read once more.
    answers.tracks = [take('Last Hours'), take('Weightless')];
    answers.run = { ...liveRow, ended_at: '2026-11-15T00:05:00Z', duration_s: 300, outcome: 'completed' };
    store.dispatch(envelope('run.state', { ...runRunning, state: 'idle', previous_state: 'running' }));
    store.dispatch(envelope('run.finished', { run: answers.run }));
    expect(await within(table).findByText('Weightless')).toBeInTheDocument();
  });

  it('reads the run again when its state changes, not for the counters sent once a second', async () => {
    answers.items = [liked];
    const store = renderPage();
    await screen.findByRole('button', { name: 'Liked Songs' });
    const runReads = () => (vi.mocked(api.GET).mock.calls as unknown[][]).filter(([path]) => path === '/api/runs/{id}').length;
    const before = runReads();

    // Counters alone: the state stays running, so nothing is read.
    store.dispatch(envelope('run.state', { ...runRunning, counters: { ...runRunning.counters, recorded: 13 }, previous_state: 'running' }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(runReads()).toBe(before);

    // A takeover pauses it: read again.
    answers.items = [{ ...liked, state: 'interrupted' }];
    store.dispatch(envelope('run.state', { ...runRunning, state: 'paused', paused_reason: 'device_moved', previous_state: 'running' }));
    await vi.waitFor(() => expect(runReads()).toBe(before + 1));
  });
});

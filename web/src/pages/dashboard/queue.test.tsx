// The queue's rows in the states the mock passes through too quickly to see (a run ends in the same
// moment as its last item) or doesn't produce (a duplicate row in the track table).

import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { queueItem, runRunning } from '@mock/fixtures.ts';
import type { QueueItem, RunTrack } from '@/api';
import { ToastProvider } from '@/components/ui-b';
import { LiveStoreProvider } from '@/state';
import { envelope, storeFor } from '@/test/live.ts';
import { CurrentItem } from './CurrentItem.tsx';
import { QueueRow } from './QueueRow.tsx';
import { UpNextRow } from './UpNextRow.tsx';

function wrap(node: React.ReactNode, store = storeFor('running')) {
  return render(
    <MemoryRouter>
      <LiveStoreProvider store={store}>
        <ToastProvider>{node}</ToastProvider>
      </LiveStoreProvider>
    </MemoryRouter>,
  );
}

function item(state: QueueItem['state'], extra: Partial<QueueItem> = {}): QueueItem {
  return queueItem({ item_id: 'x', name: 'OK Computer', state, counts: { recorded: 12, skipped: 0, failed: 0 }, ...extra });
}

function track(position: number, state: RunTrack['state'], extra: Partial<RunTrack> = {}): RunTrack {
  return { position, track_id: null, title: `Track ${position}`, artists: ['Radiohead'], duration_ms: 200_000, state, size_bytes: null, reason: null, take_id: null, ...extra };
}

describe('QueueRow', () => {
  it.each([
    ['done', 'OK Computer · 12 recorded · 0 failed', null],
    ['up_to_date', 'OK Computer · nothing new', null],
    ['carried_over', 'OK Computer · 12 recorded', 'Carried over'],
    ['stopped', 'OK Computer · 12 recorded', 'Stopped'],
  ] as const)('%s: "%s"', (state, text, pill) => {
    wrap(<QueueRow item={item(state)} />);
    expect(screen.getByText(text)).toBeInTheDocument();
    if (pill) expect(screen.getByText(pill)).toBeInTheDocument();
  });

  it('carried over: its row keeps the count, with the Carried over pill, and no Stopped', () => {
    wrap(<QueueRow item={item('carried_over', { counts: { recorded: 3, skipped: 0, failed: 0 } })} />);
    const row = screen.getByText('OK Computer · 3 recorded').closest('[data-state]');
    expect(row).toHaveAttribute('data-state', 'carried_over');
    expect(within(row as HTMLElement).getByText('Carried over')).toBeInTheDocument();
    expect(screen.queryByText('Stopped')).not.toBeInTheDocument();
  });

  it('Partial, Failed and Unavailable say why', () => {
    wrap(
      <>
        <QueueRow item={item('partial', { reason: '2 tracks failed: low volume' })} />
        <QueueRow item={item('failed', { item_id: 'y', name: 'Kid A', reason: 'The recorder stopped.' })} />
        <QueueRow item={item('unavailable', { item_id: 'z', name: 'Sunday Vinyl', reason: null })} />
      </>,
    );
    expect(screen.getByText('OK Computer · 2 tracks failed: low volume')).toBeInTheDocument();
    expect(screen.getByText('Partial')).toBeInTheDocument();
    expect(screen.getByText('Kid A · The recorder stopped.')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Sunday Vinyl · not on Spotify any more')).toBeInTheDocument();
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
  });

  it('Finishing: saving the last track, with an indeterminate bar', () => {
    wrap(<QueueRow item={item('finishing')} />);
    expect(screen.getByText('Finishing OK Computer… saving the last track')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Finishing OK Computer' })).not.toHaveAttribute('aria-valuenow');
  });
});

describe('UpNextRow', () => {
  it('shows what to expect and the ⋯ menu', () => {
    wrap(<UpNextRow item={item('up_next', { expect: { kind: 'new_tracks', count: 84 } })} />);
    expect(screen.getByText('84 new')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Options for OK Computer' })).toBeInTheDocument();
  });

  it('marks an interrupted item "Interrupted · will retry", and one carried over from the last run', () => {
    wrap(
      <>
        <UpNextRow item={item('interrupted')} />
        <UpNextRow item={item('up_next', { item_id: 'liked', name: 'Liked Songs', badges: ['carried_over_in'], expect: { kind: 'new_tracks', count: 2 } })} />
      </>,
    );
    expect(screen.getByText('Interrupted · will retry')).toBeInTheDocument();
    expect(screen.getByText('Carried over')).toBeInTheDocument();
    expect(screen.getByText('2 new')).toBeInTheDocument();
  });
});

describe('CurrentItem', () => {
  const run = { ...runRunning, state: 'running' as const };

  it('lists every track state, and counts the ones done', () => {
    const tracks = [
      track(39, 'recorded', { size_bytes: 8_400_000 }),
      track(40, 'skipped_duplicate'),
      track(41, 'failed', { reason: 'low_volume' }),
      track(42, 'recording', { take_id: 'other' }),
      track(43, 'pending'),
    ];
    wrap(<CurrentItem item={item('playing', { planned: 5 })} run={run} tracks={tracks} />);
    const rows = within(screen.getByRole('list', { name: 'Tracks' })).getAllByRole('listitem');
    expect(rows.map((r) => r.dataset.state)).toEqual(['recorded', 'skipped_duplicate', 'failed', 'recording', 'pending']);
    expect(rows[0]).toHaveTextContent('Recorded · 8.4 MB');
    expect(rows[1]).toHaveTextContent('Skipped (duplicate)');
    expect(rows[2]).toHaveTextContent('Failed · low volume');
    // Not the take the status is playing: no clock.
    expect(rows[3]).toHaveTextContent(/Recording$/);
    expect(rows[4]).toHaveTextContent('Pending');
    expect(screen.getByText('3 / 5')).toBeInTheDocument();
  });

  it('a playlist that plays whole: "n recorded", no total', () => {
    wrap(<CurrentItem item={item('playing', { planned: null, counts: { recorded: 4, skipped: 0, failed: 0 } })} run={run} tracks={[track(1, 'recorded')]} />);
    expect(screen.getByText('4 recorded')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('after Stop after this track: Stopping while the last track records to its end', () => {
    const store = storeFor('running');
    store.dispatch(envelope('session.state', { run_id: 42, item_id: 'x', state: 'stopping' }));
    wrap(<CurrentItem item={item('playing', { planned: 5 })} run={{ ...run, state: 'stopping', stop_mode: 'after_track' }} tracks={[track(1, 'recording')]} />, store);
    expect(screen.getByText('Stopping')).toBeInTheDocument();
    expect(screen.queryByText('Waiting')).not.toBeInTheDocument();
  });

  it('getting ready: no table yet', () => {
    wrap(<CurrentItem item={item('planning')} run={run} tracks={[]} />);
    expect(screen.getByText('Getting ready…')).toBeInTheDocument();
    expect(screen.getByText('Waiting')).toBeInTheDocument();
  });

  it('paused after a takeover: Interrupted, and the discarded take "Discarded · will redo"', () => {
    const store = storeFor('running');
    store.dispatch(
      envelope('device.moved', {
        run_id: 42, item_id: 'x', device: { id: 'p', name: "Lorne's iPhone", type: 'Smartphone' }, discarded_take_id: 'take-42',
      }),
    );
    const tracks = [track(41, 'recorded'), track(42, 'pending', { take_id: 'take-42' }), track(43, 'pending')];
    wrap(<CurrentItem item={item('interrupted', { planned: 3 })} run={{ ...run, state: 'paused', paused_reason: 'device_moved' }} tracks={tracks} />, store);
    expect(screen.getByText('Interrupted')).toBeInTheDocument();
    const rows = within(screen.getByRole('list', { name: 'Tracks' })).getAllByRole('listitem');
    expect(rows[1]).toHaveAttribute('data-state', 'discarded');
    expect(rows[1]).toHaveTextContent('Discarded · will redo');
    expect(rows[2]).toHaveAttribute('data-state', 'pending');
  });
});

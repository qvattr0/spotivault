import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { runRunning, type Scenario } from '@mock/fixtures.ts';
import { LiveStoreProvider, type LiveStore } from '@/state';
import { envelope, storeFor } from '@/test/live.ts';
import { NowPlaying } from './NowPlaying.tsx';


function renderStrip(store: LiveStore, docked = false) {
  return render(
    <MemoryRouter>
      <LiveStoreProvider store={store}>
        <NowPlaying docked={docked} />
      </LiveStoreProvider>
    </MemoryRouter>,
  );
}

const strip = () => screen.getByRole('region', { name: 'Now recording' });
const store = (scenario: Scenario) => storeFor(scenario);

describe('NowPlaying', () => {
  it('draws nothing when idle', () => {
    renderStrip(store('idle'));
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });

  it('shows the track, the session and Stop, and links to the Dashboard', () => {
    renderStrip(store('running'));
    expect(within(strip()).getByText('Last Hours')).toBeInTheDocument();
    expect(within(strip()).getByText('fakename · Elsewhere · track 5')).toBeInTheDocument();
    expect(within(strip()).getByText('Recording')).toBeInTheDocument();
    expect(within(strip()).getByRole('progressbar', { name: 'Track progress' })).toBeInTheDocument();
    expect(within(strip()).getByRole('link')).toHaveAttribute('href', '/dashboard');
    expect(within(strip()).getByRole('button', { name: 'Stop after this track' })).toBeEnabled();
  });

  it('follows the live events', () => {
    const s = store('running');
    renderStrip(s);
    act(() => {
      s.dispatch(
        envelope('track.started', {
          run_id: 42, item_id: 'x', take_id: 't2', artist: 'Radiohead', title: 'Airbag', album: 'OK Computer',
          length_ms: 284_000, cover_url: null, track_id: null, position: 1, planned: true,
        }),
      );
      s.dispatch(envelope('session.state', { run_id: 42, item_id: 'x', state: 'paused' }));
    });
    expect(within(strip()).getByText('Airbag')).toBeInTheDocument();
    expect(within(strip()).getByText('4:44')).toBeInTheDocument();
    expect(within(strip()).getByText('Paused')).toBeInTheDocument();
  });

  it('counts the items once the queue is known', () => {
    const s = store('running');
    renderStrip(s);
    expect(within(strip()).queryByText(/^Item /)).not.toBeInTheDocument();
    const current = s.getState().status!.item!;
    act(() => s.dispatch(envelope('run.queue', { run_id: 42, queue: [{ ...current, item_id: 'a', state: 'done' }, current] })));
    expect(within(strip()).getByText('Item 2 of 2')).toBeInTheDocument();
  });

  it('says a stop is coming', () => {
    const s = store('running');
    renderStrip(s);
    act(() => s.dispatch(envelope('run.state', { ...runRunning, stop_mode: 'after_track', previous_state: 'running' })));
    expect(within(strip()).getByRole('button', { name: 'Stopping after this track…' })).toBeDisabled();
    expect(within(strip()).getByText('Stopping')).toBeInTheDocument();
    // openapi.yaml: Stop now after "after this track" upgrades the stop, so the arrow stays.
    expect(within(strip()).getByRole('button', { name: 'More ways to stop' })).toBeEnabled();

    act(() => s.dispatch(envelope('run.state', { ...runRunning, state: 'stopping', stop_mode: 'now', previous_state: 'running' })));
    expect(within(strip()).getByRole('button', { name: 'More ways to stop' })).toBeDisabled();
  });

  it('keeps the track clock running while a stop waits for the track to end', () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    try {
      vi.setSystemTime(Date.parse('2026-11-15T01:00:00Z'));
      const s = store('running');
      act(() =>
        s.dispatch(
          envelope('track.started', {
            run_id: 42, item_id: 'x', take_id: 't2', artist: 'Radiohead', title: 'Airbag', album: 'OK Computer',
            length_ms: 240_000, cover_url: null, track_id: null, position: 1, planned: true,
          }, '2026-11-15T01:00:00Z'),
        ),
      );
      renderStrip(s);
      act(() => vi.advanceTimersByTime(30_000));
      expect(within(strip()).getByText('0:30')).toBeInTheDocument();

      act(() => s.dispatch(envelope('run.state', { ...runRunning, state: 'stopping', stop_mode: 'after_track', previous_state: 'running' })));
      expect(within(strip()).getByText('Stopping')).toBeInTheDocument();
      act(() => vi.advanceTimersByTime(10_000));
      expect(within(strip()).getByText('0:40')).toBeInTheDocument();

      // Paused: the clock stands still.
      act(() => s.dispatch(envelope('session.state', { run_id: 42, item_id: 'x', state: 'paused' })));
      act(() => vi.advanceTimersByTime(10_000));
      expect(within(strip()).getByText('0:40')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('docked on the Dashboard, has no Stop and no link', () => {
    renderStrip(store('running'), true);
    expect(within(strip()).queryByRole('button', { name: /Stop/ })).not.toBeInTheDocument();
    expect(within(strip()).queryByRole('link')).not.toBeInTheDocument();
    expect(within(strip()).getByText('fakename · track 5')).toBeInTheDocument();
  });

  it('asks before Stop now', async () => {
    const user = userEvent.setup();
    renderStrip(store('running'));
    await user.click(within(strip()).getByRole('button', { name: 'More ways to stop' }));
    await user.click(screen.getByRole('menuitem', { name: 'Stop now' }));
    const dialog = screen.getByRole('dialog', { name: 'Stop now?' });
    expect(dialog).toHaveTextContent('The current track will be discarded and recorded next time.');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

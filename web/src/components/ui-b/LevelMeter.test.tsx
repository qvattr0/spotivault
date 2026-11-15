import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LiveStoreProvider } from '@/state';
import { envelope, storeFor } from '@/test/live.ts';
import { LevelMeter } from './LevelMeter.tsx';
import { LiveLevelMeter, SILENCE_AFTER_MS } from './LiveLevelMeter.tsx';

/** How many of the meter's segments are lit, read from their classes. */
function litCount(): number {
  return screen.getByRole('meter').querySelectorAll('.accent, .warn').length;
}

function level(peak: number) {
  return envelope('level', { peak_dbfs: peak, rms_dbfs: peak - 14, channels: [] });
}

describe('LevelMeter', () => {
  it('draws 24 segments, lit up to the peak, yellow at the top', () => {
    render(<LevelMeter peakDbfs={-15} />);
    const meter = screen.getByRole('meter', { name: 'Recording level' });
    expect(meter.children).toHaveLength(24);
    expect(meter.querySelectorAll('.accent')).toHaveLength(15);
    expect(meter.querySelectorAll('.warn')).toHaveLength(2);
    expect(meter).toHaveAttribute('aria-valuetext', '-15 dBFS');
  });

  it('is silent with no reading', () => {
    render(<LevelMeter peakDbfs={null} />);
    expect(litCount()).toBe(0);
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuetext', 'Silent');
  });
});

describe('LiveLevelMeter', () => {
  afterEach(() => vi.useRealTimers());

  it('follows the live level events without re-rendering its parent', () => {
    const store = storeFor('running');
    let parentRenders = 0;
    function Strip() {
      parentRenders++;
      return <LiveLevelMeter />;
    }
    render(
      <LiveStoreProvider store={store}>
        <Strip />
      </LiveStoreProvider>,
    );
    expect(parentRenders).toBe(1);

    // A second of readings at 10 a second.
    for (let i = 0; i < 10; i++) {
      act(() => store.dispatch(level(-20 + i)));
    }
    expect(litCount()).toBe(19); // -11 dBFS
    expect(parentRenders).toBe(1);
  });

  it('falls to silence when the readings stop', () => {
    vi.useFakeTimers();
    const store = storeFor('running');
    render(
      <LiveStoreProvider store={store}>
        <LiveLevelMeter />
      </LiveStoreProvider>,
    );
    act(() => store.dispatch(level(-6)));
    expect(litCount()).toBe(22);

    act(() => {
      vi.advanceTimersByTime(SILENCE_AFTER_MS - 100);
    });
    expect(litCount()).toBe(22);
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(litCount()).toBe(0);

    // The next reading lights it again.
    act(() => store.dispatch(level(-30)));
    expect(litCount()).toBe(10);
  });
});

import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { envelope, storeFor } from '@/test/live.ts';
import { useLevel, useStatus } from './hooks.ts';
import { LiveStoreProvider } from './LiveStoreProvider.tsx';

describe('live hooks', () => {
  it('re-render the level meter on level events, and nothing else', () => {
    const store = storeFor('running');
    const renders = { status: 0, meter: 0 };

    function StatusLine() {
      renders.status += 1;
      return <p>{useStatus()?.state}</p>;
    }
    function Meter() {
      renders.meter += 1;
      const reading = useLevel();
      return <p>peak {reading?.level.peak_dbfs ?? 'none'}</p>;
    }

    render(
      <LiveStoreProvider store={store}>
        <StatusLine />
        <Meter />
      </LiveStoreProvider>,
    );
    for (let i = 1; i <= 10; i++) {
      act(() => store.dispatch(envelope('level', { peak_dbfs: -i, rms_dbfs: -20, channels: [] })));
    }

    expect(screen.getByText('peak -10')).toBeInTheDocument();
    expect(renders.meter).toBe(11);
    expect(renders.status).toBe(1);

    act(() => store.dispatch(envelope('session.state', { run_id: 42, item_id: 'x', state: 'paused' })));
    expect(screen.getByText('peak none')).toBeInTheDocument();
    expect(screen.getByText('running')).toBeInTheDocument();
  });
});

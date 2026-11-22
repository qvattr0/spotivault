// The run header's live counters: Skipped counts only tracks the run skipped without recording
// them. Tracks already saved are skipped too, but they're the normal look of a run, not news.

import { render, within, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { runRunning } from '@mock/fixtures.ts';
import { ToastProvider } from '@/components/ui-b';
import { LiveStoreProvider } from '@/state';
import { storeFor } from '@/test/live.ts';
import { RunHeader, SKIPPED_HINT } from './RunHeader.tsx';

describe('the run header counters', () => {
  it("doesn't count tracks already saved as skipped", () => {
    const run = { ...runRunning, counters: { ...runRunning.counters, recorded: 3, skipped_duplicate: 230, skipped_other: 2, failed: 1 } };
    render(
      <MemoryRouter>
        <LiveStoreProvider store={storeFor('running')}>
          <ToastProvider>
            <RunHeader run={run} />
          </ToastProvider>
        </LiveStoreProvider>
      </MemoryRouter>,
    );
    const counters = within(screen.getByRole('group', { name: 'Counters' }));
    expect(counters.getByText(/Recorded 3/)).toBeInTheDocument();
    expect(counters.getByText(/Skipped 2/)).toHaveAttribute('title', SKIPPED_HINT);
    expect(counters.getByText(/Failed 1/)).toBeInTheDocument();
  });
});

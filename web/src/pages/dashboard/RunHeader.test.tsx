// The run header's line: the same text as before ("started 01:00 · 0:42 elapsed · …"), with each
// dot drawn as its own element so it gets room around it, ending with this run's own time left.

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { runRunning } from '@mock/fixtures.ts';
import type { RunSummary } from '@/api';
import { ToastProvider } from '@/components/ui-b';
import { LiveStoreProvider } from '@/state';
import { storeFor } from '@/test/live.ts';
import { RunHeader } from './RunHeader.tsx';

function renderHeader(run: RunSummary) {
  return render(
    <MemoryRouter>
      <LiveStoreProvider store={storeFor('running')}>
        <ToastProvider>
          <RunHeader run={run} />
        </ToastProvider>
      </LiveStoreProvider>
    </MemoryRouter>,
  );
}

const runLine = () => screen.getByText((_, element) => element?.tagName === 'P' && /^started /.test(element.textContent ?? ''));

describe('the run header', () => {
  it("ends its line with this run's own time left, not the backlog's", () => {
    // storeFor('running') has the mock's backlog: about 27 h left of the whole library.
    const windowEnd = new Date(Date.now() + 6 * 3_600_000).toISOString();
    renderHeader({ ...runRunning, window_end: windowEnd, time_left: { seconds: 540, unknown_items: 0, as_of: new Date().toISOString() } });
    expect(runLine().textContent).toMatch(/ · Scheduled · stops by \d\d:\d\d · about 9 min left in this run$/);
    expect(runLine().textContent).not.toMatch(/27 h/);
  });

  it('says nothing of time left while the run starts', () => {
    renderHeader({ ...runRunning, state: 'starting', time_left: null });
    expect(runLine().textContent).toMatch(/ · stops by \d\d:\d\d$/);
  });

  it('spaces the dots in the run line, and keeps its text', () => {
    const { container } = render(
      <MemoryRouter>
        <LiveStoreProvider store={storeFor('running')}>
          <ToastProvider>
            <RunHeader run={runRunning} />
          </ToastProvider>
        </LiveStoreProvider>
      </MemoryRouter>,
    );
    const line = screen.getByText(
      (_, element) => element?.tagName === 'P' && /^started \d\d:\d\d · \d+:\d\d elapsed · Scheduled · stops by \d\d:\d\d/.test(element.textContent ?? ''),
    );
    expect(line.querySelectorAll('.metaDot')).toHaveLength(line.textContent!.split(' · ').length - 1);
    expect(container.querySelector('.metaDot')?.textContent).toBe('·');
  });
});

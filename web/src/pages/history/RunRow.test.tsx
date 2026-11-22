// The Runs table's rows (History · Runs): a run's counts, outcome and link, and a row for a run
// that didn't happen (no link, no counts).

import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import type { HistoryRow } from '@/api';
import { RunRow } from './RunRow.tsx';

const run: HistoryRow = {
  id: 41,
  kind: 'run',
  trigger: 'scheduled',
  started_at: '2026-11-16T01:00:00Z',
  ended_at: '2026-11-16T06:12:00Z',
  duration_s: 18_720,
  outcome: 'completed_with_issues',
  counters: { recorded: 84, skipped_duplicate: 1204, skipped_other: 2, failed: 3, bytes_added: 641_728_512 },
  reason: null,
  window: null,
};

function renderRow(row: HistoryRow) {
  render(
    <MemoryRouter>
      <div role="table" aria-label="Runs">
        <div role="rowgroup">
          <RunRow row={row} />
        </div>
      </div>
    </MemoryRouter>,
  );
  return screen.getByRole('row');
}

describe('RunRow', () => {
  it('shows a run with its trigger, length, outcome and counts, and links to its page', () => {
    const row = renderRow(run);
    expect(within(row).getByRole('link')).toHaveAttribute('href', '/history/runs/41');
    expect(within(row).getByText('Scheduled')).toBeVisible();
    expect(within(row).getByText('5 h 12 m')).toBeVisible();
    expect(within(row).getByText('Completed with issues')).toBeVisible();
    expect(within(row).getByText('1,204')).toBeVisible(); // ↷ counts the duplicates, as web-ui.md says
    expect(within(row).getByText('3')).toBeVisible();
    expect(within(row).getByText('+642 MB')).toBeVisible();
  });

  it('shows a dash for the size when nothing was added', () => {
    const row = renderRow({ ...run, counters: { ...run.counters!, bytes_added: 0 } });
    expect(within(row).getByText('—')).toBeVisible();
  });

  it('draws a row for a run that did not happen greyed, with no link and no counts', () => {
    const row = renderRow({ id: 36, kind: 'missed', trigger: 'scheduled', started_at: '2026-11-10T01:00:00Z', ended_at: null, duration_s: null, outcome: null, counters: null, reason: 'not_running', window: null });
    expect(within(row).getByText('Missed: spotivault was not running')).toBeVisible();
    expect(within(row).queryByRole('link')).toBeNull();
  });
});

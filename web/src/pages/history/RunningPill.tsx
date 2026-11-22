// A run that is still going, in History. The controller's listRuns includes it (history.py: "a run
// still going included"), with no end and no outcome yet. Its counters are written only as items
// end, so History shows "Running", linking to the Dashboard, in place of its outcome and counts.

import { CircleDotDashed } from 'lucide-react';
import type { HistoryRow } from '@/api';
import { Pill } from '@/components/ui-a';

/** Whether a History row is a run still going. */
export function isRunning(row: HistoryRow): boolean {
  return row.kind === 'run' && row.outcome === null && row.ended_at === null;
}

/** The pill in place of a running run's outcome: the Dashboard shows the run live. */
export function RunningPill() {
  return (
    <Pill tone="green" icon={CircleDotDashed} to="/dashboard">
      Running
    </Pill>
  );
}

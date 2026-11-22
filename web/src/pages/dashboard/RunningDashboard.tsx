import type { RunSummary } from '@/api';
import { NowPlaying } from '@/shell';
import { RunAlerts } from './RunAlerts.tsx';
import { RunHeader } from './RunHeader.tsx';
import { RunQueue } from './RunQueue.tsx';

/**
 * The Dashboard while a run is going (web-ui.md § Running: queue-first; t4YEY, hJlHj): the run
 * header, the now-playing strip docked under it (the global bottom bar is hidden here), the
 * warnings, then the queue.
 */
export function RunningDashboard({ run }: { run: RunSummary }) {
  return (
    <>
      <RunHeader run={run} />
      <NowPlaying docked />
      <RunAlerts run={run} />
      <RunQueue run={run} />
    </>
  );
}

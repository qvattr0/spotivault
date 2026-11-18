import { Page } from '@/shell';
import { useStatus } from '@/state';
import { IdleDashboard } from './IdleDashboard.tsx';
import { RunningDashboard } from './RunningDashboard.tsx';

/**
 * /dashboard (web-ui.md § Dashboard): idle, or a run going. The live store switches it between the
 * two as run.state events arrive. Its tint is a darker green while a run is going (t4YEY, hJlHj).
 */
export function DashboardPage() {
  const status = useStatus();
  const run = status && status.state !== 'idle' ? status.run : null;
  return (
    <Page tint={run ? 'dashboard-running' : 'dashboard'}>
      {run ? <RunningDashboard run={run} /> : <IdleDashboard />}
    </Page>
  );
}

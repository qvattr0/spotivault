import { PageTabs } from '@/shell';

/**
 * History's tabs (web-ui.md § History): Runs and Logs. The Tracks tab isn't in M1, so it isn't
 * offered (no dead links).
 */
export function HistoryTabs() {
  return (
    <PageTabs
      label="History"
      tabs={[
        { to: '/history/runs', label: 'Runs' },
        { to: '/history/logs', label: 'Logs' },
      ]}
    />
  );
}

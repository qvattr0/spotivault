// The Library's Refresh button, at the right of the filter chips (web-ui.md § Header): reads the
// Library from Spotify now, so a playlist made or followed in Spotify shows without waiting for
// the next page open or run. "Refreshing…" with a spinner until its refresh ends, then a toast
// says what it found (use-library-refresh.ts). Not disabled meanwhile, so keyboard focus stays.
// During a backup it's greyed out with `aria-disabled`, as the Player's Restart is, and its
// tooltip says why; a backup that starts after the press is refused with a toast.

import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui-a';
import { Tooltip } from '@/components/ui-b';
import { useStatus } from '@/state';
import { REFRESH_ERRORS, REFRESH_HINT } from './library-words.ts';
import { useLibraryRefresh } from './use-library-refresh.ts';

export function RefreshButton() {
  const { refresh, refreshing } = useLibraryRefresh();
  const status = useStatus();
  const runGoing = status !== null && status.state !== 'idle';
  return (
    <Tooltip label={runGoing ? REFRESH_ERRORS.run_active : REFRESH_HINT} align="end">
      <Button
        variant="secondary"
        icon={RefreshCw}
        busy={refreshing}
        aria-disabled={runGoing || undefined}
        onClick={() => void refresh()}
      >
        {refreshing ? 'Refreshing…' : 'Refresh'}
      </Button>
    </Tooltip>
  );
}

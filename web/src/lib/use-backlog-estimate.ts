// useBacklogEstimate(): the backlog estimate for the Dashboard's Full backup card and wizard step 9.
//
// Two sources, and the newer one wins, by `as_of` (newestBacklog):
// - the live store's: the hello's `backlog` snapshot, then each `backlog` event;
// - GET /api/backlog, read when the page opens. That read is what asks the controller for a
//   catalog refresh, at most once every 15 minutes (design.md § Backlog estimate: "the figures
//   refresh when the page opens"). The store never reads it, for that reason (web/README.md).
//
// It's read again when a catalog refresh ends. The controller works the estimate out again after
// each refresh, but sends a `backlog` event only when a figure changed, so without this read the
// "Updated" time would stay at the older estimate's. Only `ended` counts: a read while a refresh
// runs would ask for another one, since the 15 minutes count from the last refresh that finished.
// After `ended`, that read's own refresh request is held back by the 15 minutes.

import { api, useApi, type ApiError, type Backlog } from '@/api';
import { useBacklog, useLiveEvent } from '@/state';
import { newestBacklog } from './backlog-words.ts';

export interface BacklogEstimate {
  /** The newest estimate, or null before the first one. */
  backlog: Backlog | null;
  /** Why GET /api/backlog failed, or null. */
  error: ApiError | null;
}

export function useBacklogEstimate(): BacklogEstimate {
  const live = useBacklog();
  const read = useApi((signal) => api.GET('/api/backlog', { signal }), []);
  useLiveEvent('catalog.refresh', ({ data }) => {
    if (data.state === 'ended') read.reload();
  });
  return { backlog: newestBacklog(live, read.data ?? null), error: read.error };
}

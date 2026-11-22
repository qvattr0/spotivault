// The Runs tab's rows: the first page through useApi(), then the pages after it, as you scroll
// (web-ui.md § Runs tab: "loading more as you scroll"). A new first page (a run finished, or the
// filter changed) drops the pages loaded after the old one: they belong to the list they came
// after, so they count only while that first page is still the one on screen.

import { useState } from 'react';
import { api, useApi, type HistoryRow } from '@/api';
import { useAction } from '@/lib/use-action.ts';
import { useLiveEvent } from '@/state';

/** The filter chips (openapi.yaml, listRuns: `filter`). */
export type RunFilter = 'all' | 'with_issues' | 'scheduled' | 'run_now';

interface LaterPages {
  /** The first page these came after (its object identity). */
  after: unknown;
  rows: HistoryRow[];
  cursor: string | null;
}

export function useRunList(filter: RunFilter) {
  // A finished run adds a row at the top, so the first page is read again. The pages after it
  // are dropped with it (see above), and the user loads them again as they scroll.
  const first = useApi((signal) => api.GET('/api/runs', { params: { query: { filter } }, signal }), [filter], {
    reloadOn: ['run.finished'],
  });
  // A run that starts joins the list at once, as the controller lists it (RunRow: Running). Only its
  // start: its numbers aren't shown until it ends, so the other run.state events change nothing.
  useLiveEvent('run.state', (event) => {
    if (event.data.previous_state === 'idle' && event.data.state !== 'idle') first.reload();
  });
  const [later, setLater] = useState<LaterPages | null>(null);

  const page = first.data;
  const more = later && page && later.after === page ? later : null;
  const rows = [...(page?.runs ?? []), ...(more?.rows ?? [])];
  const cursor = more ? more.cursor : (page?.next_cursor ?? null);

  const fetchMore = useAction(
    (from: string) => api.GET('/api/runs', { params: { query: { filter, cursor: from } } }),
    {
      // The closure is the render the click came from, so `page` and `more` are the list on screen then.
      onDone: (next) => {
        if (page) setLater({ after: page, rows: [...(more?.rows ?? []), ...next.runs], cursor: next.next_cursor });
      },
    },
  );

  return {
    rows,
    cursor,
    loading: first.loading,
    error: first.error,
    loadingMore: fetchMore.busy,
    loadMore: () => {
      if (cursor) void fetchMore.run(cursor);
    },
  };
}

// The Library's Refresh button (web-ui.md § Header): POST /api/library/refresh, then wait for its
// refresh's `catalog.refresh` `ended` (events.md), and say what it found in a toast. The list
// itself follows the `library.item` events the refresh sends, as for any other change.
//
// Which `ended` is ours: the answer names the refresh that was already running (`refresh_id`), or
// none when ours waits for its turn. Then it's the next `manual` one to start after the press (or
// one dropped before it started): a `manual` refresh that started earlier, another tab's, isn't
// ours, even if it ends while the request is out. The socket can beat the answer, so the events
// that come while the request is out are kept and checked against it.

import { useEffect, useRef, useState } from 'react';
import { CircleAlert } from 'lucide-react';
import { api, callApi } from '@/api';
import { useToast } from '@/components/ui-b';
import { errorText } from '@/lib/errors.ts';
import { useLive, useLiveEvent, type CatalogRefreshEvent } from '@/state';
import { REFRESH_ERRORS, refreshedText } from './library-words.ts';

/** Stop waiting, quietly, if no `ended` came by then: the controller may have restarted. */
export const REFRESH_GIVE_UP_MS = 5 * 60_000;

interface Waiting {
  /** The answer: the refresh this press joined, or null when ours has no id yet. Unset while the request is out. */
  answer?: { refreshId: number | null };
  /** The refreshes whose `started` came after the press. */
  started: Set<number>;
  /** The `ended` events that came while the request was out. */
  early: CatalogRefreshEvent[];
}

function isOurs(event: CatalogRefreshEvent, refreshId: number | null, started: Set<number>): boolean {
  if (event.state !== 'ended') return false;
  if (refreshId !== null) return event.refresh_id === refreshId;
  return event.trigger === 'manual' && (event.refresh_id === null || started.has(event.refresh_id));
}

export function useLibraryRefresh() {
  const toast = useToast();
  const resyncs = useLive((s) => s.resyncs);
  const [refreshing, setRefreshing] = useState(false);
  const waiting = useRef<Waiting | null>(null);

  function stop() {
    waiting.current = null;
    setRefreshing(false);
  }

  function finish(event: CatalogRefreshEvent) {
    stop();
    toast.show(refreshedText(event), event.outcome === 'ok' ? {} : { icon: CircleAlert });
  }

  useLiveEvent('catalog.refresh', ({ data }) => {
    const now = waiting.current;
    if (now === null) return;
    if (data.state === 'started') {
      if (data.refresh_id !== null) now.started.add(data.refresh_id);
    } else if (!now.answer) {
      now.early.push(data);
    } else if (isOurs(data, now.answer.refreshId, now.started)) {
      finish(data);
    }
  });

  // Events may have been missed (a reconnect, a seq gap): its `ended` may never come. The page's
  // lists reload on their own after a resync.
  const seenResyncs = useRef(resyncs);
  useEffect(() => {
    if (resyncs === seenResyncs.current) return;
    seenResyncs.current = resyncs;
    if (waiting.current?.answer) stop();
  }, [resyncs]);

  useEffect(() => {
    if (!refreshing) return;
    const timer = setTimeout(stop, REFRESH_GIVE_UP_MS);
    return () => clearTimeout(timer);
  }, [refreshing]);

  async function refresh() {
    if (waiting.current) return; // one press at a time: the button says Refreshing…
    const press: Waiting = { started: new Set(), early: [] };
    waiting.current = press;
    setRefreshing(true);
    const result = await callApi(api.POST('/api/library/refresh'));
    if (waiting.current !== press) return;
    if (result.error) {
      stop();
      toast.show(errorText(result.error, REFRESH_ERRORS), { icon: CircleAlert });
      return;
    }
    const refreshId = result.data.refresh_id;
    press.answer = { refreshId };
    const ended = press.early.find((event) => isOurs(event, refreshId, press.started));
    if (ended) finish(ended);
  }

  return { refresh, refreshing };
}

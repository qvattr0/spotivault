// useApi(): page data read through REST, kept fresh.
//
//   const library = useApi((signal) => api.GET('/api/library', { params: { query: { filter } }, signal }), [filter]);
//   if (library.loading) return <Skeleton />;
//   if (library.error) return <Alert>{wording[library.error.code]}</Alert>;
//   return <List items={library.data.items} />;
//
// - It loads when the component mounts and whenever a value in `deps` changes (like useEffect).
// - It loads again after the live store resynced (a reconnect, a seq gap): events may have been
//   missed meanwhile, so the data may be stale.
// - `reloadOn: ['run.finished']` loads again on those live events. For frequent events that carry
//   the change (library.item, album.item), patch the data with setData() in useLiveEvent instead.
// - Reloads (reloadOn and reload()) never pile up: while one is out, more requests make one more
//   reload, sent RELOAD_GAP_MS after that answer. A burst of events (tracks during a fast duplicate
//   replay) then costs a request now and then, and each answer lands instead of being cut off.
// - `keepData: true` keeps the last answer on screen while new `deps` load (a search as you type,
//   a filter chip), instead of going back to `data: undefined`. `loading` is still true meanwhile.
//
// TanStack Query would add caching shared between components; the pages don't need it yet (one
// user, a LAN, and the socket pushes most changes), so this small hook does instead.

import { useCallback, useEffect, useEffectEvent, useRef, useState } from 'react';
import { useLive, useLiveStore } from '../state/hooks.ts';
import type { EventType } from '../state/events.ts';
import { callApi, type ApiError, type FetchResult } from './call.ts';

export interface ApiState<T> {
  /** The answer. Undefined until it arrives, and while new `deps` load. */
  data: T | undefined;
  /** Why the latest load failed, or null. A failed reload keeps the older data. */
  error: ApiError | null;
  /** True until the first answer for the current `deps`. Reloads keep the data on screen instead. */
  loading: boolean;
  /** Loads again, keeping the current data on screen until the answer comes. */
  reload(): void;
  /** Changes the loaded data in place, for a live event that carries the change. */
  setData(update: (data: T) => T): void;
}

export interface UseApiOptions {
  /** Live events that make the data stale: it loads again when one arrives. */
  reloadOn?: readonly EventType[];
  /** While new `deps` load, keep showing the answer for the old ones (lists with a search box). */
  keepData?: boolean;
}

/** The pause between a reload's answer and the one more reload asked for while it was out. */
export const RELOAD_GAP_MS = 300;

interface Answer<T> {
  /** Which `deps` it answers (counts up each time they change). */
  version: number;
  data: T | undefined;
  error: ApiError | null;
}

export function useApi<T>(
  request: (signal: AbortSignal) => Promise<FetchResult<T>>,
  deps: readonly unknown[],
  options: UseApiOptions = {},
): ApiState<T> {
  const store = useLiveStore();
  const resyncs = useLive((s) => s.resyncs);

  // A new version whenever a value in `deps` changes (React's "adjust state while rendering").
  const [seen, setSeen] = useState({ deps, version: 0 });
  let version = seen.version;
  if (!sameValues(seen.deps, deps)) {
    version += 1;
    setSeen({ deps, version });
  }

  const [answer, setAnswer] = useState<Answer<T> | null>(null);
  const [reloads, setReloads] = useState(0);
  const send = useEffectEvent((signal: AbortSignal) => request(signal));
  // `out`: a request is out, or one more is about to go. `again`: a reload was asked for meanwhile.
  // Refs, not state: they change between renders, and nothing on screen depends on them.
  const out = useRef(false);
  const again = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let pause: ReturnType<typeof setTimeout> | undefined;
    out.current = true;
    again.current = false; // this request already sees what those reloads were for
    void callApi(send(controller.signal)).then((result) => {
      if (controller.signal.aborted) return;
      setAnswer((old) => {
        const oldData = old?.version === version ? old.data : undefined;
        return result.error
          ? { version, data: oldData, error: result.error }
          : { version, data: result.data, error: null };
      });
      if (again.current) {
        pause = setTimeout(() => setReloads((n) => n + 1), RELOAD_GAP_MS);
      } else {
        out.current = false;
      }
    });
    return () => {
      controller.abort();
      clearTimeout(pause);
      out.current = false;
    };
  }, [version, resyncs, reloads]);

  const reload = useCallback(() => {
    if (out.current) again.current = true;
    else setReloads((n) => n + 1);
  }, []);

  const reloadOn = options.reloadOn?.join(' ') ?? '';
  useEffect(() => {
    if (!reloadOn) return;
    const stops = reloadOn.split(' ').map((type) => store.onEvent(type as EventType, reload));
    return () => stops.forEach((stop) => stop());
  }, [store, reloadOn, reload]);

  const setData = useCallback((update: (data: T) => T) => {
    setAnswer((old) => (old && old.data !== undefined ? { ...old, data: update(old.data) } : old));
  }, []);

  const current = answer?.version === version ? answer : null;
  return {
    data: current ? current.data : options.keepData ? answer?.data : undefined,
    error: current?.error ?? null,
    loading: current === null,
    reload,
    setData,
  };
}

function sameValues(a: readonly unknown[], b: readonly unknown[]): boolean {
  return a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
}

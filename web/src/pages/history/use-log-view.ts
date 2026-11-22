// The Logs tab's lines (web-ui.md § Logs tab): the newest page from GET /api/logs, older pages as
// you scroll up, and the live tail from `log.lines` (events.md § Logs).
//
// - **Following:** at the bottom, new lines are added and the oldest dropped past MAX_LINES, so
//   the page never holds more than that. Scrolled up (paused), new lines wait in `pending`, and
//   "Jump to latest" adds them. If more than MAX_LINES wait, or older pages pushed lines off the
//   bottom, the view has a gap: Jump to latest reads the newest page again instead.
// - **A filter change** starts over: a new `logs.follow` (with a new follow_id, so a batch on its
//   way under the old filter is dropped) and the newest page. Live lines that arrive before that
//   page are kept and merged into it; a line both bring is shown once (by `id`).
// - **A reconnect** (a new hello): lines written while the socket was down came by neither way.
//   Following, the newest page is read again and merged. If more came than that page holds, the
//   view starts again from that page, and scrolling up reads the lines before it in order. Paused,
//   the view gets a gap.
// - **A page with no lines but a cursor:** a page reads at most about 8 MB (openapi.yaml listLogs),
//   so a sparse search or level filter can find nothing in it. The first read and "Load older
//   lines" each read on by themselves READ_ON more times.
// - **Dropped:** the controller sends at most 200 lines per batch. The ones it leaves out are
//   counted, and the tab offers to read them (Reload).

import { useCallback, useEffect, useReducer, useRef } from 'react';
import { api, callApi, type ApiError, type LogLevel, type LogLine, type LogPage, type LogSource } from '@/api';
import { useLiveEvent, useLiveStore } from '@/state';

/** The most lines the page holds, live or loaded. */
export const MAX_LINES = 2000;
/** Lines per page read. */
export const PAGE_LINES = 200;
/** A page can come back empty with a cursor (a search that found nothing in what it read): read this many more by itself. */
export const READ_ON = 3;

export interface LogQuery {
  /** The Source chips that are on; none: every source. */
  sources: LogSource[];
  /** The Level chips that are on; none: every level but debug. */
  levels: LogLevel[];
  run: number | null;
  /** The search, as typed (sent once it's settled). */
  q: string;
}

interface State {
  status: 'loading' | 'ready' | 'error';
  error: ApiError | null;
  /** Oldest first. */
  lines: LogLine[];
  /** The cursor for older lines, or null when there are none. */
  older: string | null;
  loadingOlder: boolean;
  /** At the bottom: new lines show as they come. */
  following: boolean;
  /** New lines while paused. */
  pending: LogLine[];
  /** Lines after the last one shown were left out: Jump to latest reads the newest page again. */
  gap: boolean;
  /** Lines the live tail left out since the last full read. */
  dropped: number;
}

type Action =
  | { type: 'start' }
  | { type: 'loaded'; page: LogPage; early: LogLine[] }
  | { type: 'failed'; error: ApiError }
  | { type: 'live'; lines: LogLine[]; dropped: number }
  | { type: 'older-start' }
  | { type: 'older'; page: LogPage | null }
  | { type: 'newest'; page: LogPage; after: string | null }
  | { type: 'follow' }
  | { type: 'pause' };

const INITIAL: State = {
  status: 'loading',
  error: null,
  lines: [],
  older: null,
  loadingOlder: false,
  following: true,
  pending: [],
  gap: false,
  dropped: 0,
};

/** Compares two lines' ids (`<at_ns>-<dup>-<service>`) as the controller orders them: time, service, dup. */
export function compareIds(a: string, b: string): number {
  const [nsA = '', dupA = '0', ...restA] = a.split('-');
  const [nsB = '', dupB = '0', ...restB] = b.split('-');
  if (nsA.length !== nsB.length) return nsA.length - nsB.length;
  if (nsA !== nsB) return nsA < nsB ? -1 : 1;
  const serviceA = restA.join('-');
  const serviceB = restB.join('-');
  if (serviceA !== serviceB) return serviceA < serviceB ? -1 : 1;
  return Number(dupA) - Number(dupB);
}

/** Both lists as one, in order, each line once. */
export function mergeLines(a: readonly LogLine[], b: readonly LogLine[]): LogLine[] {
  if (b.length === 0) return a.slice();
  if (a.length === 0) return dedupe(b.slice().sort((x, y) => compareIds(x.id, y.id)));
  const last = a[a.length - 1];
  // The usual case: every new line is newer than the last one.
  if (last && b.every((line) => compareIds(line.id, last.id) > 0)) return [...a, ...dedupe(b.slice())];
  return dedupe([...a, ...b].sort((x, y) => compareIds(x.id, y.id)));
}

function dedupe(lines: LogLine[]): LogLine[] {
  const seen = new Set<string>();
  return lines.filter((line) => (seen.has(line.id) ? false : (seen.add(line.id), true)));
}

/** Keeps the newest MAX_LINES; the oldest kept line becomes the cursor for the ones dropped. */
function keepNewest(state: State, lines: LogLine[]): Pick<State, 'lines' | 'older'> {
  if (lines.length <= MAX_LINES) return { lines, older: state.older };
  const kept = lines.slice(-MAX_LINES);
  return { lines: kept, older: kept[0]?.id ?? state.older };
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'start':
      return INITIAL;
    case 'loaded': {
      const lines = mergeLines(action.page.lines, action.early);
      return { ...INITIAL, status: 'ready', ...keepNewest({ ...INITIAL, older: action.page.next_before }, lines) };
    }
    case 'failed':
      return { ...state, status: 'error', error: action.error };
    case 'live': {
      const dropped = state.dropped + action.dropped;
      if (state.following) return { ...state, dropped, ...keepNewest(state, mergeLines(state.lines, action.lines)) };
      if (state.gap) return { ...state, dropped };
      const pending = mergeLines(state.pending, action.lines);
      if (pending.length > MAX_LINES) return { ...state, dropped, pending: [], gap: true };
      return { ...state, dropped, pending };
    }
    case 'older-start':
      return { ...state, loadingOlder: true };
    case 'older': {
      if (!action.page) return { ...state, loadingOlder: false };
      const lines = mergeLines(action.page.lines, state.lines);
      if (lines.length <= MAX_LINES) return { ...state, loadingOlder: false, lines, older: action.page.next_before };
      // Too many: the newest go, and the view has a gap below until Jump to latest.
      return { ...state, loadingOlder: false, lines: lines.slice(0, MAX_LINES), older: action.page.next_before, gap: true, pending: [] };
    }
    case 'newest': {
      // After a reconnect: following, merge the newest page in; paused, there's a gap.
      if (!state.following) return { ...state, gap: true, pending: [] };
      const { page, after } = action;
      const oldest = page.lines[0];
      // More lines came while the socket was down than the page holds: the ones between the last
      // line shown (`after`) and the page are unread. Start from the page; scrolling up reads them.
      if (oldest && page.next_before !== null && (after === null || compareIds(oldest.id, after) > 0)) {
        const since = state.lines.filter((line) => compareIds(line.id, oldest.id) >= 0);
        const restart = { ...state, older: page.next_before };
        return { ...restart, gap: false, ...keepNewest(restart, mergeLines(page.lines, since)) };
      }
      return { ...state, ...keepNewest(state, mergeLines(state.lines, page.lines)) };
    }
    case 'follow': {
      if (state.following) return state;
      const merged = mergeLines(state.lines, state.pending);
      return { ...state, following: true, pending: [], ...keepNewest(state, merged) };
    }
    case 'pause':
      return state.following ? { ...state, following: false } : state;
  }
}

/** GET /api/logs with the query's filters. */
function readOnePage(query: LogQuery, before: string | null, signal?: AbortSignal) {
  return callApi(
    api.GET('/api/logs', {
      params: {
        query: {
          source: query.sources.length ? query.sources : undefined,
          level: query.levels.length ? query.levels : undefined,
          run: query.run ?? undefined,
          q: query.q || undefined,
          before: before ?? undefined,
          limit: PAGE_LINES,
        },
      },
      signal,
    }),
  );
}

/** A page, and up to READ_ON more while they come back with no lines but a cursor. */
async function readPage(query: LogQuery, before: string | null, signal?: AbortSignal) {
  let result = await readOnePage(query, before, signal);
  for (let more = 0; more < READ_ON; more += 1) {
    const page = result.data;
    if (!page || page.lines.length > 0 || page.next_before === null || signal?.aborted) break;
    result = await readOnePage(query, page.next_before, signal);
  }
  return result;
}

export interface LogView extends State {
  /** Reads the page before the oldest line shown (scrolled to the top). */
  loadOlder(): void;
  /** At the bottom: show new lines as they come (and the ones that waited). */
  follow(): void;
  /** Scrolled up: new lines wait. */
  pause(): void;
  /** "Jump to latest": the waiting lines, or the newest page again after a gap. */
  jumpToLatest(): void;
  /** Reads everything again (after an error, or lines the live tail left out). */
  reload(): void;
}

let nextFollowId = 1;

export function useLogView(query: LogQuery): LogView {
  const store = useLiveStore();
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const followId = useRef(0);
  /** Live lines that came before the first page did. */
  const early = useRef<LogLine[] | null>(null);
  const reads = useRef(0);
  const [restarts, restart] = useReducer((n: number) => n + 1, 0);
  const key = JSON.stringify(query);

  // A filter change (or reload): follow with the new filter and read the newest page.
  useEffect(() => {
    const q: LogQuery = JSON.parse(key) as LogQuery;
    const id = nextFollowId++;
    followId.current = id;
    early.current = [];
    reads.current += 1;
    dispatch({ type: 'start' });
    store.followLogs({
      follow_id: id,
      filter: { source: q.sources.length ? q.sources : null, level: q.levels.length ? q.levels : null, run: q.run, q: q.q || null },
    });
    const controller = new AbortController();
    void readPage(q, null, controller.signal).then((result) => {
      if (controller.signal.aborted || followId.current !== id) return;
      const waiting = early.current ?? [];
      early.current = null;
      if (result.error) dispatch({ type: 'failed', error: result.error });
      else dispatch({ type: 'loaded', page: result.data, early: waiting });
    });
    return () => controller.abort();
  }, [key, store, restarts]);

  // Leaving the tab: stop following.
  useEffect(() => () => store.followLogs(null), [store]);

  useLiveEvent('log.lines', (event) => {
    if (event.data.follow_id !== followId.current) return; // under an earlier filter
    if (early.current) {
      early.current.push(...event.data.lines);
      return;
    }
    dispatch({ type: 'live', lines: event.data.lines, dropped: event.data.dropped });
  });

  // A hello on a socket that was down: read the newest page again (the store sends the follow again).
  useLiveEvent('hello', () => {
    if (state.status !== 'ready') return;
    const id = followId.current;
    const after = state.lines.at(-1)?.id ?? null;
    void readOnePage(JSON.parse(key) as LogQuery, null).then((result) => {
      if (followId.current === id && !result.error) dispatch({ type: 'newest', page: result.data, after });
    });
  });

  const loadOlder = useCallback(() => {
    if (state.status !== 'ready' || state.loadingOlder || state.older === null) return;
    const id = followId.current;
    const q = JSON.parse(key) as LogQuery;
    dispatch({ type: 'older-start' });
    void readPage(q, state.older).then((result) => {
      if (followId.current === id) dispatch({ type: 'older', page: result.error ? null : result.data });
    });
  }, [key, state.status, state.loadingOlder, state.older]);

  // With a gap below, the lines after the last one shown are gone: read the newest page again.
  const jumpToLatest = useCallback(() => {
    if (state.gap) restart();
    else dispatch({ type: 'follow' });
  }, [state.gap]);

  return {
    ...state,
    loadOlder,
    follow: jumpToLatest,
    pause: useCallback(() => dispatch({ type: 'pause' }), []),
    jumpToLatest,
    reload: restart,
  };
}

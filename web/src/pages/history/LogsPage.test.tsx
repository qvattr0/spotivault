// History › Logs (web-ui.md § Logs tab): its states, with GET /api/logs stubbed and `log.lines`
// played through the store: loading, empty, filtered (chips, the run, the search), following the
// live tail, paused with "Jump to latest", the lines the live tail left out, pages that read
// nothing (a sparse search), a reconnect after a long gap, a run that doesn't exist, and what
// screen readers hear.

import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, type LogLine, type LogPage } from '@/api';
import { ToastProvider } from '@/components/ui-b';
import { LiveStoreProvider, type LiveStore, type LogFollow } from '@/state';
import { helloFor } from '@mock/fixtures.ts';
import { envelope, storeFor } from '@/test/live.ts';
import { LogsPage } from './LogsPage.tsx';
import { compareIds, MAX_LINES, mergeLines, READ_ON } from './use-log-view.ts';

let n = 0;
function logLine(message: string, extra: Partial<LogLine> = {}): LogLine {
  n += 1;
  const at = new Date(Date.UTC(2026, 10, 15, 1, 0, n)).toISOString();
  const ns = `${Date.parse(at)}000000`;
  return { id: `${ns}-0-controller`, at, source: 'controller', service: 'controller', level: 'info', message, run_id: null, ...extra };
}

type Query = { source?: string[]; level?: string[]; run?: number; q?: string; before?: string };
/** An error answer, for `pages` to give. */
type Refusal = { status: number; error: { error: { code: string; message: string } } };
let pages: (query: Query) => LogPage | Refusal | Promise<LogPage>;
let logQueries: Query[];

beforeEach(() => {
  n = 0;
  logQueries = [];
  pages = () => ({ lines: [], next_before: null });
  vi.spyOn(api, 'GET').mockImplementation(((path: string, init?: { params?: { query?: Query } }) => {
    if (path === '/api/runs') {
      const runs = [
        { id: 41, kind: 'run', trigger: 'scheduled', started_at: '2026-11-14T00:00:00Z', ended_at: '2026-11-14T05:00:00Z', duration_s: 18000, outcome: 'completed', counters: null, reason: null, window: null },
      ];
      return Promise.resolve({ data: { runs, next_cursor: null }, response: new Response(null, { status: 200 }) });
    }
    if (path === '/api/logs/download') {
      return Promise.resolve({ data: new Blob(['zip']), response: new Response(null, { status: 200 }) });
    }
    const query = init?.params?.query ?? {};
    logQueries.push(query);
    return Promise.resolve(pages(query)).then((data) =>
      'status' in data
        ? { error: data.error, response: new Response(null, { status: data.status }) }
        : { data, response: new Response(null, { status: 200 }) },
    );
  }) as never);
});

afterEach(() => vi.restoreAllMocks());

function renderPage(path = '/history/logs') {
  const store = storeFor('idle');
  const follow = vi.spyOn(store, 'followLogs');
  render(
    <MemoryRouter initialEntries={[path]}>
      <LiveStoreProvider store={store}>
        <ToastProvider>
          <Routes>
            <Route path="/history/logs" element={<LogsPage />} />
          </Routes>
        </ToastProvider>
      </LiveStoreProvider>
    </MemoryRouter>,
  );
  return { store, follow };
}

/** The follow_id of the latest logs.follow. */
function followId(follow: { mock: { calls: (LogFollow | null)[][] } }): number {
  const last = follow.mock.calls.map(([arg]) => arg).filter((arg) => arg != null).at(-1);
  if (!last) throw new Error('not following');
  return last.follow_id;
}

function live(store: LiveStore, lines: LogLine[], id: number, dropped = 0) {
  act(() => store.dispatch(envelope('log.lines', { lines, dropped, follow_id: id })));
}

function shownMessages(): string[] {
  const log = screen.getByRole('log', { name: 'Log lines' });
  return Array.from(log.querySelectorAll('[data-line-id]')).map((row) => row.lastElementChild?.textContent ?? '');
}

/** jsdom has no layout: give the scroller a size and a position, then scroll it. */
function scrollTo(top: number) {
  const log = screen.getByRole('log', { name: 'Log lines' });
  Object.defineProperty(log, 'scrollHeight', { configurable: true, value: 4000 });
  Object.defineProperty(log, 'clientHeight', { configurable: true, value: 400 });
  Object.defineProperty(log, 'scrollTop', { configurable: true, writable: true, value: top });
  fireEvent.scroll(log);
}

describe('History › Logs', () => {
  it('says it is loading, then that there are no lines yet', async () => {
    let answer!: (page: LogPage) => void;
    pages = () => new Promise((resolve) => (answer = resolve));
    renderPage();
    expect(await screen.findByText('Loading logs…')).toBeInTheDocument();
    await act(async () => answer({ lines: [], next_before: null }));
    expect(await screen.findByText('No log lines yet.')).toBeInTheDocument();
    expect(screen.getByText('Logs rotate after 14 days or 50 MB, whichever comes first.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Logs' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('link', { name: 'Tracks' })).not.toBeInTheDocument();
  });

  it('follows with the filters and reads the page again when a chip, the run or the search changes', async () => {
    const user = userEvent.setup();
    const { follow } = renderPage();
    expect(await screen.findByText('No log lines yet.')).toBeInTheDocument();
    expect(follow).toHaveBeenLastCalledWith({ follow_id: expect.any(Number), filter: { source: null, level: null, run: null, q: null } });

    await user.click(within(screen.getByRole('group', { name: 'Level' })).getByRole('button', { name: 'Error' }));
    await user.click(within(screen.getByRole('group', { name: 'Source' })).getByRole('button', { name: 'Spytify' }));
    expect(within(screen.getByRole('group', { name: 'Source' })).getByRole('button', { name: 'Spytify' })).toHaveAttribute('aria-pressed', 'true');
    expect(await screen.findByText('No lines match these filters.')).toBeInTheDocument();
    expect(logQueries.at(-1)).toMatchObject({ source: ['spytify'], level: ['error'] });
    expect(follow).toHaveBeenLastCalledWith({ follow_id: expect.any(Number), filter: { source: ['spytify'], level: ['error'], run: null, q: null } });

    await user.selectOptions(screen.getByRole('combobox', { name: 'Run' }), '41');
    await vi.waitFor(() => expect(logQueries.at(-1)).toMatchObject({ run: 41 }));

    await user.type(screen.getByRole('searchbox', { name: 'Search logs' }), 'timeout');
    // The read comes once the search has settled (250 ms), in an effect after that render.
    await vi.waitFor(() => expect(logQueries.at(-1)).toMatchObject({ q: 'timeout', run: 41, level: ['error'] }));
    expect(await screen.findByText('No lines match “timeout”.')).toBeInTheDocument();
  });

  it('opens on the run in the address: "Logs for this run"', async () => {
    const { follow } = renderPage('/history/logs?run=41');
    await screen.findByText('No lines match these filters.');
    expect(logQueries[0]).toMatchObject({ run: 41 });
    expect(follow).toHaveBeenLastCalledWith(expect.objectContaining({ filter: expect.objectContaining({ run: 41 }) }));
    expect(screen.getByRole('combobox', { name: 'Run' })).toHaveValue('41');
  });

  it('follows the live tail at the bottom, and drops batches from an earlier filter', async () => {
    pages = () => ({ lines: [logLine('first'), logLine('second', { level: 'warning' })], next_before: null });
    const { store, follow } = renderPage();
    expect(await screen.findByText('second')).toBeInTheDocument();
    const id = followId(follow);
    live(store, [logLine('third', { level: 'error', source: 'spytify', service: '41-liked', run_id: 41 })], id);
    live(store, [logLine('from an older follow')], id - 1);
    expect(shownMessages()).toEqual(['first', 'Warning: second', 'Error: third']);
    // A message that starts with its level's word isn't given it twice.
    live(store, [logLine('Warning: no GPU found', { level: 'warning', source: 'client', service: 'spotify' })], id);
    live(store, [logLine('error: gave up', { level: 'error' })], id);
    expect(shownMessages().slice(-2)).toEqual(['Warning: no GPU found', 'error: gave up']);
    const third = screen.getByText('third').closest('[data-line-id]');
    expect(third).toHaveAttribute('data-level', 'error');
    expect(within(third as HTMLElement).getByText('Spytify')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Jump to latest/ })).not.toBeInTheDocument();
  });

  it('pauses when scrolled up: new lines wait for "Jump to latest"', async () => {
    const user = userEvent.setup();
    pages = () => ({ lines: [logLine('first'), logLine('second')], next_before: null });
    const { store, follow } = renderPage();
    await screen.findByText('second');
    scrollTo(1000);
    const jump = await screen.findByRole('button', { name: /Jump to latest/ });
    live(store, [logLine('while paused')], followId(follow));
    expect(screen.queryByText('while paused')).not.toBeInTheDocument();
    expect(jump).toHaveTextContent('1 new line');
    await user.click(jump);
    expect(await screen.findByText('while paused')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Jump to latest/ })).not.toBeInTheDocument();
    // The pill went away under the focus: the log has it now, not the page.
    expect(screen.getByRole('log', { name: 'Log lines' })).toHaveFocus();
  });

  it('keeps "Load older lines" focusable while it loads, outside the scrolled lines', async () => {
    const user = userEvent.setup();
    let answer!: (page: LogPage) => void;
    const olderLine = logLine('older');
    pages = (query) =>
      query.before ? new Promise((resolve) => (answer = resolve)) : { lines: [logLine('newest')], next_before: 'cursor-1' };
    renderPage();
    await screen.findByText('newest');
    const older = screen.getByRole('button', { name: 'Load older lines' });
    // Focusing it must not scroll the lines (and pause the tail): it isn't inside them.
    expect(screen.getByRole('log', { name: 'Log lines' })).not.toContainElement(older);
    await user.click(older);
    expect(older).toHaveTextContent('Loading older lines…');
    expect(older).toHaveAttribute('aria-disabled', 'true');
    expect(older).toBeEnabled();
    expect(older).toHaveFocus();
    await user.click(older); // ignored while it loads
    expect(logQueries.filter((query) => query.before)).toHaveLength(1);
    await act(async () => answer({ lines: [olderLine], next_before: 'cursor-2' }));
    expect(shownMessages()).toEqual(['older', 'newest']);
    expect(older).toHaveFocus();
    expect(older).toHaveTextContent('Load older lines');
  });

  it('reads on by itself when the first page found nothing in what it read', async () => {
    const empty = (cursor: string): LogPage => ({ lines: [], next_before: cursor });
    pages = (query) => {
      if (!query.before) return empty('c1');
      if (query.before === 'c1') return empty('c2');
      return { lines: [logLine('crashed: at last')], next_before: 'c3' };
    };
    renderPage();
    expect(await screen.findByText('crashed: at last')).toBeInTheDocument();
    expect(logQueries.map((query) => query.before ?? null)).toEqual([null, 'c1', 'c2']);
    expect(screen.getByRole('button', { name: 'Load older lines' })).toBeInTheDocument();
  });

  it('says the newest logs have no match, and offers older lines, when reading on found nothing', async () => {
    const user = userEvent.setup();
    let reads = 0;
    pages = (query) => {
      reads += 1;
      if (query.q && reads > 2 * (READ_ON + 1)) return { lines: [logLine('crashed: long ago')], next_before: null };
      return { lines: [], next_before: `c${reads}` };
    };
    renderPage();
    expect(await screen.findByText('No lines to show in the newest logs.')).toBeInTheDocument();
    await user.type(screen.getByRole('searchbox', { name: 'Search logs' }), 'crashed');
    expect(await screen.findByText('No lines match “crashed” in the newest logs.')).toBeInTheDocument();
    expect(logQueries.filter((query) => query.q)).toHaveLength(READ_ON + 1);
    await user.click(screen.getByRole('button', { name: 'Load older lines' }));
    expect(await screen.findByText('crashed: long ago')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load older lines' })).not.toBeInTheDocument();
    expect(screen.getByRole('log', { name: 'Log lines' })).toHaveFocus();
  });

  it('after a reconnect with more lines missed than a page holds, starts from the newest page', async () => {
    const [a, b] = [logLine('before the drop'), logLine('last before the drop')];
    const missed = Array.from({ length: 3 }, (_, i) => logLine(`while offline ${i + 1}`));
    let answer: LogPage = { lines: [a, b], next_before: null };
    pages = () => answer;
    const { store, follow } = renderPage();
    await screen.findByText('last before the drop');
    // The newest page doesn't reach back to the last line shown: the lines between are unread.
    answer = { lines: missed.slice(1), next_before: missed[1]?.id ?? null };
    const after = logLine('after the reconnect');
    act(() => store.dispatch(envelope('hello', helloFor('idle'))));
    live(store, [after], followId(follow));
    await vi.waitFor(() => expect(shownMessages()).toEqual(['while offline 2', 'while offline 3', 'after the reconnect']));
    answer = { lines: [missed[0] as LogLine], next_before: null };
    scrollTo(0);
    await vi.waitFor(() => expect(shownMessages()).toEqual(['while offline 1', 'while offline 2', 'while offline 3', 'after the reconnect']));
    expect(logQueries.at(-1)).toMatchObject({ before: missed[1]?.id });
  });

  it('after a reconnect within a page, merges the newest lines in', async () => {
    const [a, b, c] = [logLine('one'), logLine('two'), logLine('three')];
    let answer: LogPage = { lines: [a, b], next_before: null };
    pages = () => answer;
    const { store } = renderPage();
    await screen.findByText('two');
    answer = { lines: [b, c], next_before: a.id };
    act(() => store.dispatch(envelope('hello', helloFor('idle'))));
    await vi.waitFor(() => expect(shownMessages()).toEqual(['one', 'two', 'three']));
  });

  it('a run that doesn\'t exist offers all runs, not a retry', async () => {
    const user = userEvent.setup();
    pages = (query) =>
      query.run ? { status: 404, error: { error: { code: 'not_found', message: 'No run with this id.' } } } : { lines: [logLine('every run')], next_before: null };
    renderPage('/history/logs?run=999');
    expect(await screen.findByText("There's no run with that number.")).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show all runs' }));
    expect(await screen.findByText('every run')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Run' })).toHaveValue('all');
  });

  it('tells screen readers which service wrote a System or Spytify line', async () => {
    pages = () => ({
      lines: [
        logLine('(WW) Option "-nolisten" is deprecated', { source: 'system', service: 'xserver', level: 'warning' }),
        logLine('track.started "Ribs"', { source: 'spytify', service: '41-liked', run_id: 41 }),
        logLine('runs: run 41 started'),
      ],
      next_before: null,
    });
    renderPage();
    await screen.findByText('runs: run 41 started');
    const badges = Array.from(screen.getByRole('log', { name: 'Log lines' }).querySelectorAll('[data-line-id] > span:first-of-type'));
    expect(badges.map((badge) => badge.textContent)).toEqual(['System, xserver', 'Spytify, 41-liked', 'Controller']);
  });

  it('reads older lines when scrolled to the top', async () => {
    const older = logLine('older');
    pages = (query) =>
      query.before ? { lines: [older], next_before: null } : { lines: [logLine('newest')], next_before: 'cursor-1' };
    renderPage();
    await screen.findByText('newest');
    scrollTo(0);
    expect(await screen.findByText('older')).toBeInTheDocument();
    expect(logQueries.at(-1)).toMatchObject({ before: 'cursor-1' });
    expect(shownMessages()).toEqual(['older', 'newest']);
  });

  it('counts the lines the live tail left out, and reads them with "Show them"', async () => {
    const user = userEvent.setup();
    const { store, follow } = renderPage();
    await screen.findByText('No log lines yet.');
    live(store, [logLine('one of many')], followId(follow), 250);
    expect(await screen.findByText(/250 lines came too fast to show live/)).toBeInTheDocument();
    const reads = logQueries.length;
    await user.click(screen.getByRole('button', { name: 'Show them' }));
    await vi.waitFor(() => expect(logQueries.length).toBe(reads + 1));
    expect(screen.queryByText(/came too fast/)).not.toBeInTheDocument();
  });

  it('downloads the last 7 days as a zip', async () => {
    const user = userEvent.setup();
    const created = vi.fn(() => 'blob:zip');
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Download last 7 days (.zip)' }));
    await vi.waitFor(() => expect(click).toHaveBeenCalled());
    expect(api.GET).toHaveBeenCalledWith('/api/logs/download', expect.objectContaining({ params: { query: { days: 7 } }, parseAs: 'blob' }));
    expect(created).toHaveBeenCalled();
  });
});

describe('the lines, merged', () => {
  it('orders ids by time, then service, then dup, whatever their length', () => {
    expect(compareIds('999-0-controller', '1000-0-controller')).toBeLessThan(0);
    expect(compareIds('1000-0-controller', '1000-0-dbus')).toBeLessThan(0);
    expect(compareIds('1000-1-42-liked', '1000-0-42-liked')).toBeGreaterThan(0);
  });

  it('keeps each line once, in order', () => {
    const [a, b, c] = [logLine('a'), logLine('b'), logLine('c')] as [LogLine, LogLine, LogLine];
    expect(mergeLines([a, b], [b, c]).map((l) => l.message)).toEqual(['a', 'b', 'c']);
    expect(mergeLines([b, c], [a]).map((l) => l.message)).toEqual(['a', 'b', 'c']);
    expect(mergeLines([], [c, a, a]).map((l) => l.message)).toEqual(['a', 'c']);
    expect(MAX_LINES).toBe(2000);
  });
});

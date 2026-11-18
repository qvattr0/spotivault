import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { helloFor, historyRows } from '@mock/fixtures.ts';
import { LiveStoreProvider } from '@/state/LiveStoreProvider.tsx';
import { envelope, storeFor } from '@/test/live.ts';
import type { LiveStore } from '@/state/store.ts';
import type { FetchResult } from './call.ts';
import { useApi } from './use-api.ts';

/** A request that answers `data` (200), or the error envelope for `code` (409). */
function answer<T>(data: T): Promise<FetchResult<T>> {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) });
}
function failure<T>(code: string): Promise<FetchResult<T>> {
  return Promise.resolve({ error: { error: { code, message: code, details: null } }, response: new Response(null, { status: 409 }) });
}

function wrapperFor(store: LiveStore) {
  return ({ children }: { children: ReactNode }) => <LiveStoreProvider store={store}>{children}</LiveStoreProvider>;
}

describe('useApi', () => {
  it('loads on mount, and again when deps change', async () => {
    const request = vi.fn((filter: string) => answer({ filter }));
    const { result, rerender } = renderHook(({ filter }) => useApi(() => request(filter), [filter]), {
      initialProps: { filter: 'all' },
      wrapper: wrapperFor(storeFor('idle')),
    });
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.data).toEqual({ filter: 'all' }));
    expect(result.current.loading).toBe(false);

    rerender({ filter: 'tracked' });
    // New deps: the old answer isn't shown for them.
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeUndefined();
    await waitFor(() => expect(result.current.data).toEqual({ filter: 'tracked' }));
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('keeps the old answer on screen while new deps load, with keepData', async () => {
    let release: (() => void) | null = null;
    const request = (filter: string) =>
      filter === 'all' ? answer({ filter }) : new Promise<FetchResult<{ filter: string }>>((resolve) => (release = () => void resolve(answer({ filter }))));
    const { result, rerender } = renderHook(({ filter }) => useApi(() => request(filter), [filter], { keepData: true }), {
      initialProps: { filter: 'all' },
      wrapper: wrapperFor(storeFor('idle')),
    });
    await waitFor(() => expect(result.current.data).toEqual({ filter: 'all' }));

    rerender({ filter: 'tracked' });
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toEqual({ filter: 'all' });
    await waitFor(() => expect(release).not.toBeNull());
    act(() => release?.());
    await waitFor(() => expect(result.current.data).toEqual({ filter: 'tracked' }));
    expect(result.current.loading).toBe(false);
  });

  it('gives the error code of a failed load', async () => {
    const { result } = renderHook(() => useApi(() => failure('not_connected'), []), { wrapper: wrapperFor(storeFor('idle')) });
    await waitFor(() => expect(result.current.error?.code).toBe('not_connected'));
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeUndefined();
  });

  it('loads again after the live store resynced, keeping the data on screen meanwhile', async () => {
    const store = storeFor('idle');
    let n = 0;
    const { result } = renderHook(() => useApi(() => answer(++n), []), { wrapper: wrapperFor(store) });
    await waitFor(() => expect(result.current.data).toBe(1));

    act(() => store.dispatch(envelope('hello', helloFor('idle')))); // a reconnect
    expect(result.current.data).toBe(1);
    expect(result.current.loading).toBe(false);
    await waitFor(() => expect(result.current.data).toBe(2));
  });

  it('loads again on the live events in reloadOn, and on reload()', async () => {
    const store = storeFor('idle');
    let n = 0;
    const { result } = renderHook(() => useApi(() => answer(++n), [], { reloadOn: ['run.finished'] }), {
      wrapper: wrapperFor(store),
    });
    await waitFor(() => expect(result.current.data).toBe(1));

    act(() => store.dispatch(envelope('run.finished', { run: historyRows[0]! })));
    await waitFor(() => expect(result.current.data).toBe(2));

    act(() => store.dispatch(envelope('backlog', helloFor('idle').backlog!)));
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe(3));
  });

  it('does not pile up reloads: events while one is out make one more, and the one out lands', async () => {
    const store = storeFor('idle');
    const releases: (() => void)[] = [];
    const signals: AbortSignal[] = [];
    let n = 0;
    const request = vi.fn((signal: AbortSignal) => {
      signals.push(signal);
      const value = ++n;
      return new Promise<FetchResult<number>>((resolve) => releases.push(() => resolve(answer(value))));
    });
    const { result } = renderHook(() => useApi(request, [], { reloadOn: ['run.finished'] }), { wrapper: wrapperFor(store) });
    await waitFor(() => expect(releases).toHaveLength(1));
    act(() => releases[0]!());
    await waitFor(() => expect(result.current.data).toBe(1));

    // A burst: the first event reloads at once; the rest wait for its answer.
    for (let i = 0; i < 5; i += 1) act(() => store.dispatch(envelope('run.finished', { run: historyRows[0]! })));
    expect(request).toHaveBeenCalledTimes(2);
    expect(signals[1]!.aborted).toBe(false);

    act(() => releases[1]!());
    await waitFor(() => expect(result.current.data).toBe(2));
    // One more, a moment after that answer, for the events that came meanwhile.
    await waitFor(() => expect(request).toHaveBeenCalledTimes(3));
    act(() => releases[2]!());
    await waitFor(() => expect(result.current.data).toBe(3));
    expect(request).toHaveBeenCalledTimes(3);
  });

  it('keeps the older data when a reload fails', async () => {
    let fail = false;
    const { result } = renderHook(() => useApi(() => (fail ? failure<number>('internal') : answer(7)), []), {
      wrapper: wrapperFor(storeFor('idle')),
    });
    await waitFor(() => expect(result.current.data).toBe(7));
    fail = true;
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.error?.code).toBe('internal'));
    expect(result.current.data).toBe(7);
  });

  it('lets a live event patch the data with setData()', async () => {
    const { result } = renderHook(() => useApi(() => answer({ items: ['a', 'b'] }), []), {
      wrapper: wrapperFor(storeFor('idle')),
    });
    await waitFor(() => expect(result.current.data).toBeDefined());
    act(() => result.current.setData((d) => ({ items: [...d.items, 'c'] })));
    expect(result.current.data).toEqual({ items: ['a', 'b', 'c'] });
  });

  it('passes an AbortSignal, aborted when the component unmounts', async () => {
    let signal: AbortSignal | null = null;
    const { result, unmount } = renderHook(
      () =>
        useApi((s) => {
          signal = s;
          return answer(1);
        }, []),
      { wrapper: wrapperFor(storeFor('idle')) },
    );
    await waitFor(() => expect(result.current.data).toBe(1));
    unmount();
    expect(signal!.aborted).toBe(true);
  });
});

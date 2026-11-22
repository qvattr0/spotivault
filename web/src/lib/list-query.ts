// The filter chips, search box and sort menu of a list page (Library, Albums, History), sent to
// the server: the list endpoints filter, search and sort themselves (openapi.yaml: listLibrary,
// listAlbums, listRuns). The page keeps what's chosen; the server does the work.
//
//   const list = useListQuery({ filter: 'all', sort: 'recently_backed_up' });
//   const library = useApi(
//     (signal) => api.GET('/api/library', { params: { query: list.query }, signal }),
//     [list.query],
//     { keepData: true },     // the old list stays on screen while a new search loads
//   );
//   <ChipGroup value={list.filter} onChange={list.setFilter} ... />
//   <SearchInput value={list.search} onChange={(e) => list.setSearch(e.target.value)} onClear={list.clearSearch} />
//   <Select value={list.sort} onChange={list.setSort} ... />
//
// The search text goes to the server 250 ms after the last key, so a word costs one request, not
// one per letter. `query` is the same object until something changes, so it can be a useApi dep.

import { useEffect, useMemo, useState } from 'react';

/** How long the search waits after the last key before asking the server. */
export const SEARCH_DELAY_MS = 250;

export interface ListQuery<F extends string, S extends string> {
  filter: F;
  sort: S;
  /** The search, once typing has paused. Left out when empty, so the URL stays clean. */
  q?: string;
}

export interface ListQueryState<F extends string, S extends string> {
  filter: F;
  setFilter: (filter: F) => void;
  /** What's in the search box, as typed. */
  search: string;
  setSearch: (text: string) => void;
  clearSearch: () => void;
  sort: S;
  setSort: (sort: S) => void;
  /** For the request: { filter, sort, q? }. A new object only when one of them changes. */
  query: ListQuery<F, S>;
}

export function useListQuery<F extends string, S extends string>(defaults: { filter: F; sort: S }): ListQueryState<F, S> {
  const [filter, setFilter] = useState<F>(defaults.filter);
  const [sort, setSort] = useState<S>(defaults.sort);
  const [search, setSearch] = useState('');
  const q = useDebouncedValue(search.trim(), SEARCH_DELAY_MS);
  const query = useMemo(() => (q ? { filter, sort, q } : { filter, sort }), [filter, sort, q]);
  return { filter, setFilter, search, setSearch, clearSearch: () => setSearch(''), sort, setSort, query };
}

/**
 * `value`, once it has stayed the same for `delayMs`. An empty string comes through at once, so
 * clearing the search shows the whole list straight away.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);
  // The empty string settles at once too (React's "adjust state while rendering"): otherwise a key
  // pressed within the delay after clearing would bring back the search from before the clear.
  if (value === '' && settled !== '') setSettled(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return value === '' ? value : settled;
}

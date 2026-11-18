// /library: the Library, as a list or a grid (web-ui.md § Library). Owner: the library builder.
//
// Two reads of the list: `everything` (no filter) counts the header's line and feeds "Back up all
// tracked now"; `shown` is what the chips, search and sort ask for. A live `library.item` patches
// both in place, so a row's status moves while a run records it.

import { useState } from 'react';
import { Play, Plus } from 'lucide-react';
import { api, useApi, type LibraryItem } from '@/api';
import { ChipGroup, IconButton, MenuButton, SearchInput, Select, ViewSwitch, type MenuItem } from '@/components/ui-a';
import { Alert, EmptyState, useToast } from '@/components/ui-b';
import { errorText } from '@/lib/errors.ts';
import { useListQuery } from '@/lib/list-query.ts';
import { useAction } from '@/lib/use-action.ts';
import { runCreatedText } from '@/lib/run-words.ts';
import { useViewMode } from '@/lib/view-mode.ts';
import { Page, PageHeader, useNow } from '@/shell';
import { useLiveEvent } from '@/state';
import { AddPlaylistsModal } from './AddPlaylistsModal.tsx';
import { LibraryGrid } from './LibraryGrid.tsx';
import { LibraryList } from './LibraryList.tsx';
import { FILTERS, SORTS, librarySummaryText, type LibraryFilter, type LibrarySort } from './library-words.ts';
import styles from './LibraryPage.module.css';

export function LibraryPage() {
  const [view, setView] = useViewMode('library');
  const [adding, setAdding] = useState(false);
  const toast = useToast();
  const list = useListQuery<LibraryFilter, LibrarySort>({ filter: 'all', sort: 'recently_backed_up' });
  const now = useNow(60_000);

  const everything = useApi((signal) => api.GET('/api/library', { params: { query: { filter: 'all' } }, signal }), []);
  const shown = useApi((signal) => api.GET('/api/library', { params: { query: list.query }, signal }), [list.query], {
    keepData: true,
  });
  const summary = useApi((signal) => api.GET('/api/library/summary', { signal }), []);

  /** Puts a changed item in both lists. An item neither list has yet means a new one: read the lists again. */
  function patch(item: LibraryItem) {
    const has = (data?: { items: LibraryItem[] }) => data?.items.some((i) => i.id === item.id) ?? false;
    if (!has(everything.data) && !has(shown.data)) {
      reloadAll();
      return;
    }
    const swap = (data: { items: LibraryItem[] }) => ({ items: data.items.map((i) => (i.id === item.id ? item : i)) });
    everything.setData(swap);
    shown.setData(swap);
  }

  function reloadAll() {
    everything.reload();
    shown.reload();
  }

  useLiveEvent('library.item', (event) => patch(event.data));

  // A change of tracking can move an item out of a "Tracked" or "Not tracked" view.
  function changed(item: LibraryItem) {
    patch(item);
    if (list.filter === 'tracked' || list.filter === 'not_tracked') shown.reload();
  }

  const items = everything.data?.items ?? [];
  const trackedIds = items.filter((item) => item.tracked).map((item) => item.id);
  const autoTrack = summary.data?.auto_track_owned ?? false;

  const setAuto = useAction((next: boolean) => api.PUT('/api/settings', { body: { auto_track_owned: next } }), {
    onDone: () => {
      summary.reload();
      reloadAll();
    },
  });
  const backUpAll = useAction(() => api.POST('/api/runs', { body: { items: trackedIds } }), {
    onDone: (created) => toast.show(runCreatedText(created)),
  });

  // The ⋯ options menu (web-ui.md § Header): the auto-track switch and Back up all tracked now.
  const optionItems: MenuItem[] = [
    { label: 'Automatically track playlists I create', checked: autoTrack, onSelect: () => void setAuto.run(!autoTrack) },
    { label: 'Back up all tracked now', icon: Play, disabled: trackedIds.length === 0, onSelect: () => void backUpAll.run() },
  ];

  const summaryText = everything.data ? librarySummaryText(items, now) : undefined;
  const failed = !!shown.error && !shown.data;

  return (
    <Page tint="dashboard">
      <PageHeader
        title="Library"
        summary={summaryText}
        actions={
          <>
            <SearchInput
              placeholder="Search in Library"
              value={list.search}
              onChange={(event) => list.setSearch(event.target.value)}
              onClear={list.clearSearch}
            />
            <Select label="Sort" value={list.sort} onChange={list.setSort} options={SORTS} />
            <ViewSwitch value={view} onChange={setView} />
            <IconButton filled icon={Plus} label="Add playlists" onClick={() => setAdding(true)} />
            <MenuButton label="Library options" items={optionItems} />
          </>
        }
        bar={<ChipGroup label="Filter" options={FILTERS} value={list.filter} onChange={list.setFilter} />}
      />

      {failed && shown.error ? <Alert tone="danger" title={errorText(shown.error)} /> : null}
      {!shown.data && !failed ? <p className={styles.loading}>Loading…</p> : null}
      {shown.data && shown.data.items.length === 0 ? (
        <EmptyState title={list.search || list.filter !== 'all' ? 'Nothing matches' : 'No playlists yet'}>
          {list.search ? 'Clear the search, or try another filter.' : null}
        </EmptyState>
      ) : null}
      {shown.data && shown.data.items.length > 0 ? (
        view === 'list' ? (
          <LibraryList items={shown.data.items} now={now} onChanged={changed} onRemoved={reloadAll} />
        ) : (
          <LibraryGrid items={shown.data.items} onChanged={changed} />
        )
      ) : null}

      {adding ? (
        <AddPlaylistsModal
          onClose={() => {
            setAdding(false);
            reloadAll();
          }}
        />
      ) : null}
    </Page>
  );
}

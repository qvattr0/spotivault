import { useRef, useState } from 'react';
import { Plus } from 'lucide-react';
import { api, useApi, type AlbumStatus } from '@/api';
import { ChipGroup, IconButton, SearchInput, Select, ViewSwitch } from '@/components/ui-a';
import { Alert, EmptyState } from '@/components/ui-b';
import { useLiveEvent } from '@/state';
import { errorText } from '@/lib/errors.ts';
import { useListQuery } from '@/lib/list-query.ts';
import { useViewMode } from '@/lib/view-mode.ts';
import { Page, PageHeader } from '@/shell';
import { FILTERS, SORTS, replaceAlbum, type AlbumFilter, type AlbumSort } from './album-data.ts';
import { summaryText } from './album-words.ts';
import { AddAlbumsModal } from './AddAlbumsModal.tsx';
import { AlbumsGrid } from './AlbumsGrid.tsx';
import { AlbumsList } from './AlbumsList.tsx';

/**
 * /albums: the albums added for recording, in a grid or a list (web-ui.md § Albums). The grid is
 * the default: the first drawing (MX2OU) is the grid, and the choice is remembered per browser.
 */
export function AlbumsPage() {
  const list = useListQuery<AlbumFilter, AlbumSort>({ filter: 'all', sort: 'recently_added' });
  const [view, setView] = useViewMode('albums', 'grid');
  const [adding, setAdding] = useState(false);

  // The server filters, searches and sorts (listAlbums). keepData: the old list stays while a
  // search or a chip loads. A run's end can change the counts, so it reloads then.
  const albums = useApi((signal) => api.GET('/api/albums', { params: { query: list.query }, signal }), [list.query], {
    keepData: true,
    reloadOn: ['run.finished'],
  });

  // album.item carries the change (status, progress): patch the row. A new status also changes
  // the summary line and which filter holds the album, and only the server knows those for the
  // whole list: read it again then (statuses change a few times per album, not every second).
  // `statuses` remembers each album's last status from its events, for albums the filter hides.
  const statuses = useRef(new Map<string, AlbumStatus>());
  useLiveEvent('album.item', (event) => {
    const album = event.data;
    const before = statuses.current.get(album.id) ?? albums.data?.items.find((item) => item.id === album.id)?.status;
    statuses.current.set(album.id, album.status);
    albums.setData((data) => replaceAlbum(data, album));
    if (before !== album.status) albums.reload();
  });

  const data = albums.data;
  const filtered = list.filter !== 'all' || list.query.q !== undefined;

  return (
    <Page tint="albums">
      <PageHeader
        title="Albums"
        summary={data ? summaryText(data.summary) : undefined}
        actions={
          <>
            <SearchInput
              label="Search albums"
              placeholder="Album or artist"
              value={list.search}
              onChange={(event) => list.setSearch(event.target.value)}
              onClear={list.clearSearch}
            />
            <Select label="Sort" options={SORTS} value={list.sort} onChange={list.setSort} />
            <ViewSwitch value={view} onChange={setView} />
            <IconButton icon={Plus} label="Add albums" filled onClick={() => setAdding(true)} />
          </>
        }
        bar={<ChipGroup label="Filter" options={FILTERS} value={list.filter} onChange={list.setFilter} />}
      />

      {albums.error && !data ? <Alert tone="danger" title={errorText(albums.error)} /> : null}

      {data && data.items.length === 0 ? (
        filtered ? (
          <EmptyState title="No albums match">Try another filter or search.</EmptyState>
        ) : (
          <EmptyState title="No albums yet">
            Add albums with +. Only the albums you add are recorded; the ones you save in Spotify wait until you add them.
          </EmptyState>
        )
      ) : null}

      {data && data.items.length > 0 ? (
        view === 'grid' ? (
          <AlbumsGrid albums={data.items} />
        ) : (
          <AlbumsList albums={data.items} onChanged={albums.reload} />
        )
      ) : null}

      {adding ? (
        <AddAlbumsModal onClose={() => setAdding(false)} onAdded={albums.reload} />
      ) : null}
    </Page>
  );
}

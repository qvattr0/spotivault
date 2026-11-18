// The Albums page's choices and the small data helpers its lists share: the filter chips, the sort
// menu (both sent to the server, which filters and sorts; openapi.yaml listAlbums), and what the
// + modal does to the lists it holds. Owner: the albums builder.

import type { Album, AlbumsSummary, SavedAlbum } from '@/api';
import type { ChipOption, SelectOption } from '@/components/ui-a';

export type AlbumFilter = 'all' | 'recorded' | 'queued' | 'partial';
export type AlbumSort = 'recently_added' | 'album' | 'artist' | 'year';

/** The filter chips (web-ui.md § Albums, Header): All · Recorded · Queued · Partial. */
export const FILTERS: ChipOption<AlbumFilter>[] = [
  { value: 'all', label: 'All' },
  { value: 'recorded', label: 'Recorded' },
  { value: 'queued', label: 'Queued' },
  { value: 'partial', label: 'Partial' },
];

/** The sort menu (web-ui.md § Albums, Header): Recently added · Album · Artist · Year. */
export const SORTS: SelectOption<AlbumSort>[] = [
  { value: 'recently_added', label: 'Recently added' },
  { value: 'album', label: 'Album' },
  { value: 'artist', label: 'Artist' },
  { value: 'year', label: 'Year' },
];

/** The body of GET /api/albums. */
export interface AlbumsAnswer {
  items: Album[];
  summary: AlbumsSummary;
}

/** The list with one album replaced by its new state (a live album.item). Unknown albums stay out. */
export function replaceAlbum(data: AlbumsAnswer, album: Album): AlbumsAnswer {
  return { ...data, items: data.items.map((item) => (item.id === album.id ? album : item)) };
}

/**
 * The saved albums the + modal offers, filtered by name as the user types. The contract sends them
 * all, most recently saved first, so the filter needs no request.
 */
export function filterSaved(items: SavedAlbum[], text: string): SavedAlbum[] {
  const needle = text.trim().toLowerCase();
  if (!needle) return items;
  return items.filter((album) => album.name.toLowerCase().includes(needle));
}

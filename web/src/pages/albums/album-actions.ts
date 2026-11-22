// What an album can do (web-ui.md § Albums): Record again and Record now, Open in Spotify, Show
// files path, Remove from Albums. The row menu and the detail view share it. Owner: the albums builder.

import { api, type Album } from '@/api';
import { useToast } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';
import { runCreatedText } from '@/lib/run-words.ts';
import { spotifyWebUrl } from '@/lib/spotify.ts';
import { filesText } from './album-words.ts';

/**
 * The album's requests. `onRemoved` runs once the album has left the page (the detail view goes
 * back to the list; the list reloads).
 */
export function useAlbumActions(onRemoved?: () => void) {
  const toast = useToast();

  // Record again and Record now: a forced run of this album (POST /api/runs with items). The toast
  // says whether it started a run or joined the current one (web-ui.md § Running).
  const record = useAction((id: string) => api.POST('/api/runs', { body: { items: [id] } }), {
    onDone: (data) => toast.show(runCreatedText(data)),
  });

  // Remove from Albums keeps the files and the History (openapi.yaml removeAlbum).
  const remove = useAction((id: string) => api.DELETE('/api/albums/{id}', { params: { path: { id } } }), {
    errors: { not_found: 'That album has already been removed.' },
    onDone: () => {
      toast.show('Removed from Albums. Its files are kept.');
      onRemoved?.();
    },
  });

  // Show files path: the folder of a recorded track, in a toast (see album-words.ts § filesText).
  const files = useAction((id: string) => api.GET('/api/albums/{id}/tracks', { params: { path: { id } } }), {
    onDone: (list) => toast.show(filesText(list)),
  });

  return { record, remove, files };
}

/** Open in Spotify: the album's page, in a new tab. */
export function openInSpotify(album: Pick<Album, 'uri'>): void {
  window.open(spotifyWebUrl(album.uri), '_blank', 'noopener');
}

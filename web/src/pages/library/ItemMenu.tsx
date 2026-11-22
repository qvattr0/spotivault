// The ⋯ menu of a Library item (web-ui.md § List view): Back up now · Open in Spotify · Show files
// path · Remove from Library (added items only). "Change cover…" isn't in M1 (custom covers are
// deferred), so it's left out, with its item.

import { ExternalLink, FolderOpen, Play, Trash2 } from 'lucide-react';
import type { LibraryItem } from '@/api';
import { MenuButton, type MenuItem } from '@/components/ui-a';
import { useToast } from '@/components/ui-b';
import { spotifyWebUrl } from '@/lib/spotify.ts';
import { useBackUp, useRemove } from './library-actions.ts';

/**
 * Where the playlist's .m3u file goes (web-ui.md § Files: `Music/Playlists/<name>.m3u`). No
 * endpoint gives the real path, so this is the name as the playlist has it; the controller makes
 * the file name safe, which can differ for a name with odd characters. Reported as a cautious choice.
 */
export function playlistFile(name: string): string {
  return `Music/Playlists/${name}.m3u`;
}

export interface ItemMenuProps {
  item: LibraryItem;
  /** After Remove from Library: the list reloads, the detail view goes back to the Library. */
  onRemoved: () => void;
}

export function ItemMenu({ item, onRemoved }: ItemMenuProps) {
  const toast = useToast();
  const backUp = useBackUp(item);
  const remove = useRemove(item, onRemoved);

  const items: MenuItem[] = [
    { label: 'Back up now', icon: Play, onSelect: () => void backUp.run() },
    { label: 'Open in Spotify', icon: ExternalLink, onSelect: () => window.open(spotifyWebUrl(item.uri), '_blank', 'noopener') },
    { label: 'Show files path', icon: FolderOpen, onSelect: () => toast.show(playlistFile(item.name), { icon: FolderOpen }) },
  ];
  if (item.removable) items.push({ label: 'Remove from Library', icon: Trash2, danger: true, onSelect: () => void remove.run() });

  return <MenuButton label={`Options for ${item.name}`} items={items} />;
}

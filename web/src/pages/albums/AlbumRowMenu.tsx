import { CircleMinus, ExternalLink, Folder, RotateCw } from 'lucide-react';
import type { Album } from '@/api';
import { MenuButton, type MenuItem } from '@/components/ui-a';
import { openInSpotify, useAlbumActions } from './album-actions.ts';

/** The ⋯ menu of an album's row (web-ui.md § List view): Record again · Open in Spotify · Show files path · Remove from Albums. */
export function AlbumRowMenu({ album, onChanged }: { album: Album; onChanged: () => void }) {
  const actions = useAlbumActions(onChanged);
  const items: MenuItem[] = [
    { label: 'Record again', icon: RotateCw, onSelect: () => void actions.record.run(album.id) },
    { label: 'Open in Spotify', icon: ExternalLink, onSelect: () => openInSpotify(album) },
    { label: 'Show files path', icon: Folder, onSelect: () => void actions.files.run(album.id) },
    { label: 'Remove from Albums', icon: CircleMinus, onSelect: () => void actions.remove.run(album.id) },
  ];
  return <MenuButton label={`Options for ${album.name}`} items={items} />;
}

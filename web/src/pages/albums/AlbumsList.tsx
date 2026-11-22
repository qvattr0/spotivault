import { useNavigate } from 'react-router';
import type { Album } from '@/api';
import { AlbumHeader, AlbumRow, ListTable } from '@/components/ui-b';
import { AlbumRowMenu } from './AlbumRowMenu.tsx';
import { AlbumStatusPill } from './AlbumStatusPill.tsx';
import { recordedText, tracksText } from './album-words.ts';

/** The list view (web-ui.md § List view, wwJXz): album, year, tracks, recorded date, status, ⋯. */
export function AlbumsList({ albums, onChanged }: { albums: Album[]; onChanged: () => void }) {
  const navigate = useNavigate();
  return (
    <ListTable label="Albums" header={<AlbumHeader />}>
      {albums.map((album) => (
        <AlbumRow
          key={album.id}
          name={album.name}
          artist={album.artist}
          coverSrc={album.cover}
          year={album.year}
          tracks={tracksText(album)}
          recorded={recordedText(album)}
          status={<AlbumStatusPill status={album.status} />}
          menu={<AlbumRowMenu album={album} onChanged={onChanged} />}
          onOpen={() => navigate(`/albums/${album.id}`)}
        />
      ))}
    </ListTable>
  );
}

import type { TrackList } from '@/api';
import { ListTable, TrackHeader, TrackRow } from '@/components/ui-b';
import { formatDuration } from '@/shell';
import { trackView } from './album-words.ts';

/** The album's track table (web-ui.md § Detail view): position, title and artist, album, length, state. */
export function AlbumTracks({ list }: { list: TrackList }) {
  return (
    <ListTable label="Tracks" header={<TrackHeader />}>
      {list.tracks.map((track, i) => {
        const view = trackView(track);
        return (
          <TrackRow
            key={`${i}`}
            position={track.position}
            title={track.title}
            artist={track.artists.join(', ')}
            album={track.album}
            duration={track.duration_ms === null ? '' : formatDuration(track.duration_ms)}
            state={view.kind}
            stateText={view.text}
            stateHint={track.path ?? undefined}
          />
        );
      })}
    </ListTable>
  );
}

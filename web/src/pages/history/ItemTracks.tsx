// An item's tracks in one run (web-ui.md § Run page, Expanded): #, title, artist and result. A
// recorded track shows its size and its file path, with a copy button. Loaded when the item opens.
// On the page of a run still going, the list grows as takes end (a take still recording isn't
// listed), so it's read again as tracks and the item move on, and once more when the run ends.

import { Copy, CircleAlert } from 'lucide-react';
import { api, useApi, type TrackResult } from '@/api';
import type { EventType } from '@/state';
import { IconButton } from '@/components/ui-a';
import { Alert, ListTable, TrackStatus, type TrackStatusKind, useToast } from '@/components/ui-b';
import { copyText } from '@/lib/clipboard.ts';
import { cx } from '@/lib/cx.ts';
import { errorText } from '@/lib/errors.ts';
import { trackResultText } from '@/lib/run-words.ts';
import { formatBytes } from '@/shell';
import styles from './ItemTracks.module.css';

interface ItemTracksProps {
  runId: number;
  itemId: string;
  /** The item's name, for the table's name for screen readers. */
  name: string;
  /** The run is the one going on: its tracks are still coming. */
  live: boolean;
}

/** A take ended (recorded, skipped or failed), or the item moved on: the list may have grown. */
const LIVE_RELOAD_ON: EventType[] = ['track.finished', 'track.skipped', 'item.state', 'run.finished'];
/** Kept once the run ends too, so the run.finished that follows `live` turning false still lands. */
const ENDED_RELOAD_ON: EventType[] = ['run.finished'];

export function ItemTracks({ runId, itemId, name, live }: ItemTracksProps) {
  const tracks = useApi(
    (signal) => api.GET('/api/runs/{id}/items/{item}/tracks', { params: { path: { id: runId, item: itemId } }, signal }),
    [runId, itemId],
    { reloadOn: live ? LIVE_RELOAD_ON : ENDED_RELOAD_ON },
  );

  if (tracks.error) return <Alert tone="danger" title={errorText(tracks.error)} />;
  if (!tracks.data) return <p className={styles.note}>Loading…</p>;
  const rows = tracks.data.tracks;
  if (rows.length === 0) return <p className={styles.note}>No tracks in this run.</p>;

  return (
    // The header row is there for screen readers only (bWcg0 draws none), so it sits among the rows.
    <ListTable label={`Tracks of ${name}`} dense>
      <TrackHeader />
      {rows.map((track, i) => (
        <TrackResultRow key={`${i}-${track.title}`} track={track} />
      ))}
    </ListTable>
  );
}

function TrackHeader() {
  return (
    <div role="row" className={cx(styles.header, 'visually-hidden')}>
      <span role="columnheader" className={styles.number}>
        #
      </span>
      <span role="columnheader">Title</span>
      <span role="columnheader">Artist</span>
      <span role="columnheader">Result</span>
      <span role="columnheader">
        <span className="visually-hidden">Copy path</span>
      </span>
    </div>
  );
}

function TrackResultRow({ track }: { track: TrackResult }) {
  const toast = useToast();
  const path = track.path;
  const recorded = track.result === 'recorded';
  const kind: TrackStatusKind = track.result === 'recorded' ? 'recorded' : track.result === 'skipped' ? 'skipped' : 'failed';
  // A recorded track says its size; the others say what happened (run-words.ts).
  const text =
    recorded && track.size_bytes !== null ? `Recorded · ${formatBytes(track.size_bytes)}` : trackResultText(track);

  async function copyPath() {
    if (!path) return;
    // copyText() also works over plain http on the LAN, where the clipboard API isn't offered.
    if (await copyText(path)) toast.show('Path copied');
    else toast.show("Couldn't copy the path. Select it and copy it by hand.", { icon: CircleAlert });
  }

  return (
    <div role="row" className={styles.row}>
      <div role="cell" className={styles.number}>
        {track.position ?? ''}
      </div>
      <div role="cell" className={styles.title}>
        {track.title || '—'}
      </div>
      <div role="cell" className={styles.artist}>
        {track.artists.join(', ')}
      </div>
      <div role="cell" className={styles.result}>
        <TrackStatus kind={kind} text={text} className={cx(styles.status, recorded && styles.statusRecorded)} />
        {recorded && path ? (
          <span className={styles.path} title={path}>
            {path}
          </span>
        ) : null}
      </div>
      <div role="cell" className={styles.copy}>
        {recorded && path ? <IconButton icon={Copy} label="Copy path" className={styles.copyButton} onClick={() => void copyPath()} /> : null}
      </div>
    </div>
  );
}

import { useEffect, useRef } from 'react';
import { Circle, CircleCheck, CircleDotDashed, CirclePause, CircleX, Redo2, type LucideIcon } from 'lucide-react';
import type { RunTrack } from '@/api';
import { cx } from '@/lib/cx.ts';
import { formatDuration, useNow } from '@/shell';
import { useStatus } from '@/state';
import { trackStateText } from './words.ts';
import styles from './Dashboard.module.css';

type Look = RunTrack['state'] | 'discarded';

/** Each state's icon and colour (components.md § Row/Track: the Dashboard's live table, 15 px icons). */
const LOOKS: Record<Look, { icon: LucideIcon; tone: string | undefined }> = {
  recorded: { icon: CircleCheck, tone: styles.trackRecorded },
  skipped_duplicate: { icon: Redo2, tone: styles.trackSkipped },
  skipped: { icon: Redo2, tone: styles.trackSkipped },
  failed: { icon: CircleX, tone: styles.trackFailed },
  recording: { icon: CircleDotDashed, tone: styles.trackRecording },
  pending: { icon: Circle, tone: styles.trackPending },
  discarded: { icon: CirclePause, tone: styles.trackDiscarded },
};

interface TrackTableProps {
  tracks: RunTrack[];
  /** The run is paused: the track clock stands still. */
  paused: boolean;
  /** Takes a takeover discarded: "Discarded · will redo" (hJlHj). */
  discarded: string[];
}

/**
 * The current item's track table (web-ui.md § Current item; t4YEY): ✓ recorded with its size,
 * ↷ skipped, ● recording with its progress, ○ pending, ✕ failed with the reason. It's a box about
 * five rows tall that scrolls to the playing track whenever a new one starts. For a playlist that
 * plays whole, the rows come as tracks start.
 */
export function TrackTable({ tracks, paused, discarded }: TrackTableProps) {
  const box = useRef<HTMLOListElement>(null);
  const looks = tracks.map((track): Look => (track.take_id && discarded.includes(track.take_id) ? 'discarded' : track.state));
  const activeIndex = looks.findIndex((look) => look === 'recording' || look === 'discarded');
  const activeKey = activeIndex === -1 ? null : `${activeIndex}:${tracks[activeIndex]?.take_id ?? ''}`;

  // Scroll the box (not the page) so the playing track shows, with one row after it.
  useEffect(() => {
    const list = box.current;
    const row = list?.querySelector<HTMLElement>('[data-active]');
    if (!list || !row) return;
    list.scrollTop = Math.max(0, row.offsetTop + row.offsetHeight * 2 - list.clientHeight);
  }, [activeKey]);

  return (
    <ol ref={box} className={styles.tracks} aria-label="Tracks">
      {tracks.map((track, i) => {
        const look = looks[i] ?? track.state;
        const { icon: Icon, tone } = LOOKS[look];
        const active = i === activeIndex;
        return (
          <li key={`${i}:${track.track_id ?? track.take_id ?? ''}`} className={cx(styles.trackRow, tone, active && styles.trackActive)} data-active={active || undefined} data-state={look}>
            <span className={styles.trackNo}>{track.position ?? ''}</span>
            <Icon size={15} aria-hidden className={styles.trackIcon} />
            <span className={styles.trackTitle}>{track.title}</span>
            <span className={styles.trackArtist}>{track.artists.join(', ')}</span>
            <span className={styles.trackState}>
              {look === 'discarded' ? 'Discarded · will redo' : look === 'recording' ? <RecordingText track={track} paused={paused} /> : trackStateText(track)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** "Recording · 2:41 / 6:23", ticking each second from the live track (t4YEY). */
function RecordingText({ track, paused }: { track: RunTrack; paused: boolean }) {
  const playing = useStatus()?.track ?? null;
  const live = playing && playing.take_id === track.take_id ? playing : null;
  const now = useNow(1000, !!live && !paused);
  if (!live) return <>Recording</>;
  const elapsed = Math.min(Math.max(now - Date.parse(live.started_at), 0), live.length_ms);
  return (
    <>
      Recording · {formatDuration(elapsed)} / {formatDuration(live.length_ms)}
    </>
  );
}

import { Link } from 'react-router';
import type { QueueItem, Status } from '@/api';
import { Pill } from '@/components/ui-a';
import { Cover, LiveLevelMeter, Progress, type CoverKind } from '@/components/ui-b';
import { cx } from '@/lib/cx.ts';
import { useQueue, useStatus } from '@/state';
import { formatDuration } from './format.ts';
import { itemPosition, sessionPill, trackClockRuns, trackLines } from './run-words.ts';
import { StopButton } from './StopButton.tsx';
import { useNow } from './use-now.ts';
import styles from './NowPlaying.module.css';

interface NowPlayingProps {
  /** On the Dashboard: a card under the run header, without its own Stop (the header has one). */
  docked?: boolean;
}

/**
 * The now-playing strip (components.md § Now-playing strip, zwk9M; web-ui.md § Now-playing strip):
 * the track, the session pill, the level meter, the track's progress and Stop. The global bottom
 * bar while a run is going; the Dashboard docks it under its header. Draws nothing when idle.
 */
export function NowPlaying({ docked = false }: NowPlayingProps) {
  const status = useStatus();
  const queue = useQueue();
  if (!status || status.state === 'idle') return null;
  return <Strip status={status} queue={queue} docked={docked} />;
}

function Strip({ status, queue, docked }: { status: Status; queue: QueueItem[] | null; docked: boolean }) {
  const { track } = status;
  const pill = sessionPill(status);
  // The clock stands still while nothing is recording.
  const now = useNow(1000, trackClockRuns(status));
  const { title, sub } = trackLines(status, docked);
  const position = itemPosition(status, queue);

  const length = track?.length_ms ?? 0;
  const elapsed = track ? Math.min(Math.max(now - Date.parse(track.started_at), 0), length) : 0;

  const trackInfo = (
    <>
      <Cover src={track?.cover_url ?? status.item?.cover} kind={coverKind(status)} size={52} />
      <span className={styles.titles}>
        <span className={styles.title}>{title}</span>
        <span className={styles.sub}>{sub}</span>
      </span>
    </>
  );

  return (
    <section className={cx(styles.strip, docked && styles.docked)} aria-label="Now recording">
      {/* web-ui.md § Navigation: the bar links to the Dashboard. */}
      {docked ? (
        <div className={styles.track}>{trackInfo}</div>
      ) : (
        <Link to="/dashboard" className={styles.track}>
          {trackInfo}
        </Link>
      )}

      <div className={styles.centre}>
        <div className={styles.stateRow}>
          <Pill tone={pill.tone} icon={pill.icon}>
            {pill.label}
          </Pill>
          <LiveLevelMeter />
        </div>
        <div className={styles.progressRow}>
          <span className={styles.time}>{formatDuration(elapsed)}</span>
          <Progress value={length ? elapsed / length : 0} label="Track progress" className={styles.progress} />
          <span className={styles.time}>{formatDuration(length)}</span>
        </div>
      </div>

      <div className={styles.right}>
        {position && (
          <span className={styles.itemCount}>
            Item {position.index} of {position.total}
          </span>
        )}
        {!docked && <StopButton run={status.run} menuAbove />}
      </div>
    </section>
  );
}

/** The track's album cover when there is one; otherwise the item's: Liked Songs' tile, an album's or a playlist's. */
function coverKind(status: Status): CoverKind {
  if (status.track?.cover_url) return 'album';
  const kind = status.item?.kind;
  return kind === 'liked' ? 'liked' : kind === 'album' ? 'album' : 'playlist';
}

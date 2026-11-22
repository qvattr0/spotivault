import { useId } from 'react';
import { CircleDotDashed, type LucideIcon } from 'lucide-react';
import type { QueueItem, RunSummary, RunTrack } from '@/api';
import { Pill, type PillTone } from '@/components/ui-a';
import { Cover } from '@/components/ui-b';
import { cx } from '@/lib/cx.ts';
import { useAlerts, useStatus, type Alert } from '@/state';
import { TrackTable } from './TrackTable.tsx';
import { itemProgress } from './words.ts';
import styles from './Dashboard.module.css';

/** Phases before the first track plays: the table isn't there yet. */
const GETTING_READY: QueueItem['state'][] = ['planning', 'preflight', 'preparing', 'starting'];

interface CurrentItemProps {
  item: QueueItem;
  run: RunSummary;
  /** The live track table (GET /api/runs/current), or [] before it's known. */
  tracks: RunTrack[];
}

/**
 * The current item, expanded inline (web-ui.md § Current item; t4YEY, hJlHj): its cover and name,
 * its progress ("41 / 88", or "n recorded" when it plays whole), a pill, and the track table that
 * ticks off live. Green while recording; yellow once a takeover interrupted it.
 */
export function CurrentItem({ item, run, tracks }: CurrentItemProps) {
  const nameId = useId();
  const status = useStatus();
  const alerts = useAlerts();
  const paused = run.state === 'paused';
  const interrupted = item.state === 'interrupted';
  const pill = itemPill(item, run, status?.session_state ?? null);
  const progress = itemProgress(item, tracks);
  // The take a takeover threw away: its row says "Discarded · will redo" while the run is paused.
  const discarded = paused ? discardedTakes(alerts, status?.track?.take_id ?? null) : [];

  return (
    <div
      className={cx(styles.current, pill.tone === 'green' && styles.currentGreen, pill.tone === 'yellow' && styles.currentYellow)}
      role="group"
      aria-labelledby={nameId}
    >
      <div className={styles.currentHead}>
        <Cover src={item.cover} kind={item.kind === 'liked' ? 'liked' : item.kind === 'album' ? 'album' : 'playlist'} size={48} />
        <div className={styles.currentTitles}>
          <p id={nameId} className={styles.currentName}>
            {item.name}
          </p>
          {progress ? (
            <div className={styles.currentProgress}>
              <ItemBar value={progress.total > 0 ? progress.done / progress.total : 0} warn={interrupted || paused} label={`${item.name} progress`} />
              <span className={styles.currentCount}>
                {progress.done} / {progress.total}
              </span>
            </div>
          ) : (
            <span className={styles.currentCount}>{item.counts.recorded} recorded</span>
          )}
        </div>
        <Pill tone={pill.tone} icon={pill.icon}>
          {pill.label}
        </Pill>
      </div>

      {tracks.length > 0 ? (
        <TrackTable tracks={tracks} paused={paused} discarded={discarded} />
      ) : interrupted ? null : (
        <p className={styles.muted}>{GETTING_READY.includes(item.state) ? 'Getting ready…' : 'Waiting for the first track…'}</p>
      )}
    </div>
  );
}

/**
 * The item's pill: Interrupted or Paused (yellow), Stopping, Recording (green), else Waiting.
 * events.md § session.state: the pill shows Waiting, Recording, Paused or Stopping. After "Stop
 * after this track" the controller's session is `stopping` while the last track records to its end.
 */
function itemPill(item: QueueItem, run: RunSummary, session: string | null): { label: string; tone: PillTone; icon?: LucideIcon } {
  if (item.state === 'interrupted') return { label: 'Interrupted', tone: 'yellow' };
  if (run.state === 'paused') return { label: 'Paused', tone: 'yellow' };
  if (session === 'stopping' || run.state === 'stopping') return { label: 'Stopping', tone: 'neutral' };
  if (session === 'recording' && item.state === 'playing') return { label: 'Recording', tone: 'green', icon: CircleDotDashed };
  return { label: 'Waiting', tone: 'neutral' };
}

/** Which takes were discarded: the one `device.moved` names, else the track playing when it paused. */
function discardedTakes(alerts: Alert[], playing: string | null): string[] {
  const moved = alerts.find((a) => a.kind === 'device_moved');
  const named = moved?.kind === 'device_moved' ? moved.event.discarded_take_id : null;
  return [named, playing].filter((id): id is string => id !== null);
}

/** The item's progress bar: green, or yellow while it's interrupted (hJlHj). */
function ItemBar({ value, warn, label }: { value: number; warn: boolean; label: string }) {
  const percent = Math.round(Math.min(Math.max(value, 0), 1) * 100);
  return (
    <div className={styles.itemBar} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
      <div className={cx(styles.itemBarFill, warn && styles.itemBarWarn)} style={{ width: `${percent}%` }} />
    </div>
  );
}

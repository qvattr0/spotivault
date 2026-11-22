import { useId } from 'react';
import { api, useApi, type CurrentRun, type RunSummary, type RunTrack } from '@/api';
import { isCurrentItemState, useQueue, useStatus, type EventType } from '@/state';
import { CurrentItem } from './CurrentItem.tsx';
import { QueueRow } from './QueueRow.tsx';
import { UpNextRow } from './UpNextRow.tsx';
import { queueSections } from './words.ts';
import styles from './Dashboard.module.css';

/**
 * The live track table changes with these: a track starts, ends or is skipped; the item moves on.
 * The events don't carry the table, so it's read again (GET /api/runs/current). useApi doesn't
 * pile the reads up: during a burst (a fast duplicate replay, about 4 events a second) one is out
 * at a time, and one more follows its answer.
 */
const TRACKS_RELOAD_ON: EventType[] = ['track.started', 'track.finished', 'track.skipped', 'item.state'];

/**
 * The queue (web-ui.md § Queue; t4YEY): QUEUE lists the items that ended, then the current one,
 * expanded with its track table; UP NEXT lists the rest. The queue itself comes from the live store
 * (run.queue and item.state); the current item's tracks from GET /api/runs/current.
 */
export function RunQueue({ run }: { run: RunSummary }) {
  const queueId = useId();
  const upNextId = useId();
  const queue = useQueue();
  const status = useStatus();
  const current = useApi((signal) => api.GET('/api/runs/current', { signal }), [run.id], { reloadOn: TRACKS_RELOAD_ON, keepData: true });

  if (queue === null) return <p className={styles.muted}>Loading the queue…</p>;
  const currentId = status?.item?.item_id ?? null;
  const sections = queueSections(queue, currentId, run.state === 'paused');
  const tracks = sections.current ? tracksOf(current.data, sections.current.item_id) : [];

  return (
    <>
      <section className={styles.queueSection} aria-labelledby={queueId}>
        <h2 id={queueId} className={styles.label}>
          Queue
        </h2>
        {sections.finished.length === 0 && !sections.current ? (
          <p className={styles.muted}>{run.state === 'starting' ? 'Building the queue…' : 'Nothing is recording right now.'}</p>
        ) : (
          <ul className={styles.queueList}>
            {sections.finished.map((item) => (
              <li key={item.item_id}>
                <QueueRow item={item} />
              </li>
            ))}
            {sections.current ? (
              <li>
                {sections.current.state === 'finishing' ? (
                  <QueueRow item={sections.current} />
                ) : (
                  <CurrentItem item={sections.current} run={run} tracks={tracks} />
                )}
              </li>
            ) : null}
          </ul>
        )}
      </section>

      {sections.upNext.length > 0 ? (
        <section className={styles.queueSection} aria-labelledby={upNextId}>
          <h2 id={upNextId} className={styles.label}>
            Up next
          </h2>
          <ul className={styles.upNextList}>
            {sections.upNext.map((item) => (
              <li key={item.item_id}>
                <UpNextRow item={item} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

/**
 * The track table, if the answer is about this item. GET /api/runs/current doesn't say whose
 * tracks they are, so they count as the item that was current in the same answer; right after the
 * next item starts, the old answer's tracks aren't shown under the new item's name.
 */
function tracksOf(data: CurrentRun | undefined, itemId: string): RunTrack[] {
  if (!data) return [];
  const owner =
    data.queue.find((q) => isCurrentItemState(q.state)) ??
    // Paused after a takeover: the interrupted item is still the current one.
    (data.run?.state === 'paused' ? data.queue.find((q) => q.item_id === itemId && q.state === 'interrupted') : undefined);
  return owner?.item_id === itemId ? data.current_tracks : [];
}

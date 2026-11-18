// One item of a run, as a collapsible row (web-ui.md § Run page): the cover, the name, the badges
// and the ✓ ↷ ✕ counts. Expanded, it shows the item's tracks for this run and Retry failed.
//
// The whole row is the toggle: an invisible button covers it (its name is its label), and the
// content sits above it without taking clicks. A button can't hold the cover's div, so this is how.

import { useId, useState } from 'react';
import { ChevronRight, CircleCheck, CircleX, Redo2, RefreshCw } from 'lucide-react';
import type { RunItem } from '@/api';
import { Button, Pill } from '@/components/ui-a';
import { Cover, type CoverKind } from '@/components/ui-b';
import { cx } from '@/lib/cx.ts';
import { BADGE } from '@/lib/run-words.ts';
import { formatCount } from '@/shell';
import { ItemTracks } from './ItemTracks.tsx';
import { useRetry } from './use-retry.ts';
import styles from './RunItemRow.module.css';

interface RunItemRowProps {
  runId: number;
  item: RunItem;
  /** The run is the one going on: an open item's tracks follow it. */
  live: boolean;
}

export function RunItemRow({ runId, item, live }: RunItemRowProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const retry = useRetry();

  return (
    <div className={cx(styles.item, open && styles.itemOpen)}>
      <div className={styles.head}>
        <button
          type="button"
          className={styles.toggle}
          aria-expanded={open}
          aria-controls={panelId}
          aria-label={item.name}
          onClick={() => setOpen(!open)}
        />
        <ChevronRight size={16} aria-hidden className={cx(styles.chevron, open && styles.open)} />
        <Cover src={item.cover} kind={coverKind(item)} size={36} />
        <div className={styles.names}>
          <span className={styles.name}>{item.name}</span>
          {item.reason ? <span className={styles.reason}>{item.reason}</span> : null}
        </div>
        <div className={styles.badges}>
          {item.badges.map((badge) => (
            <Pill key={badge} tone={BADGE[badge].tone}>
              {BADGE[badge].label}
            </Pill>
          ))}
        </div>
        <Counts counts={item.counts} />
      </div>

      {open ? (
        <div id={panelId} className={styles.panel}>
          <ItemTracks runId={runId} itemId={item.item_id} name={item.name} live={live} />
          {item.can_retry ? (
            <div className={styles.actions}>
              <Button variant="secondary" icon={RefreshCw} busy={retry.busy} onClick={() => void retry.run([item.item_id])}>
                Retry failed
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** The cover's placeholder: the heart for Liked Songs, the disc for an album, the note otherwise. */
function coverKind(item: RunItem): CoverKind {
  if (item.kind === 'liked') return 'liked';
  if (item.kind === 'album') return 'album';
  return 'playlist';
}

/**
 * ✓ recorded, ↷ skipped, ✕ failed, each in its own grid column (bWcg0): the number in text-sub,
 * the icon green for recorded, red for failures. Each has its word for screen readers.
 * (A fragment: the three spans are the row grid's last three cells.)
 */
function Counts({ counts }: { counts: RunItem['counts'] }) {
  return (
    <>
      <span className={styles.count}>
        <CircleCheck size={14} aria-hidden className={styles.recorded} />
        {formatCount(counts.recorded)}
        <span className="visually-hidden">recorded</span>
      </span>
      <span className={styles.count}>
        <Redo2 size={14} aria-hidden />
        {formatCount(counts.skipped)}
        <span className="visually-hidden">skipped</span>
      </span>
      <span className={styles.count}>
        <CircleX size={14} aria-hidden className={cx(counts.failed > 0 && styles.failed)} />
        {formatCount(counts.failed)}
        <span className="visually-hidden">failed</span>
      </span>
    </>
  );
}

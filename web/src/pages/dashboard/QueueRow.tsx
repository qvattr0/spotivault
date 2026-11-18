import { CircleArrowRight, CircleCheck, CircleDotDashed, CircleMinus, CircleSlash, CircleX, TriangleAlert, type LucideIcon } from 'lucide-react';
import type { QueueItem } from '@/api';
import { Pill, type PillTone } from '@/components/ui-a';
import { Progress } from '@/components/ui-b';
import { cx } from '@/lib/cx.ts';
import { countsText } from './words.ts';
import styles from './Dashboard.module.css';

interface RowLook {
  icon: LucideIcon;
  /** The icon's colour. */
  tone: 'accent' | 'sub' | 'warn' | 'danger';
  /** What follows the name. */
  text: string;
  pill?: { label: string; tone: PillTone };
}

/**
 * A collapsed row of the queue (web-ui.md § Queue): an item that ended in this run, or the current
 * one while it finishes. Drawn: Done ("✓ OK Computer · 12 recorded · 0 failed") and Up to date
 * ("Chill Mix · nothing new"). Not drawn: Finishing (web-ui.md gives its words), and the other
 * endings, which are ours, with the pill colours of components.md § Status pill.
 */
export function QueueRow({ item }: { item: QueueItem }) {
  if (item.state === 'finishing') {
    return (
      <div className={cx(styles.queueRow, styles.finishingRow)}>
        <span className={styles.queueRowLine}>
          <CircleDotDashed size={16} aria-hidden className={styles.sub} />
          <span className={styles.queueRowText}>Finishing {item.name}… saving the last track</span>
        </span>
        <Progress value={null} label={`Finishing ${item.name}`} />
      </div>
    );
  }

  const look = rowLook(item);
  const Icon = look.icon;
  return (
    <div className={styles.queueRow} data-state={item.state}>
      <span className={styles.queueRowLine}>
        <Icon size={16} aria-hidden className={styles[look.tone]} />
        <span className={styles.queueRowText}>
          {item.name} · {look.text}
        </span>
        {look.pill ? <Pill tone={look.pill.tone}>{look.pill.label}</Pill> : null}
      </span>
    </div>
  );
}

function rowLook(item: QueueItem): RowLook {
  switch (item.state) {
    case 'done':
      return { icon: CircleCheck, tone: 'accent', text: countsText(item) };
    case 'up_to_date':
      return { icon: CircleMinus, tone: 'sub', text: 'nothing new' };
    case 'partial':
      return { icon: TriangleAlert, tone: 'warn', text: item.reason ?? countsText(item), pill: { label: 'Partial', tone: 'yellow' } };
    case 'failed':
      return { icon: CircleX, tone: 'danger', text: item.reason ?? countsText(item), pill: { label: 'Failed', tone: 'red' } };
    case 'unavailable':
      return { icon: CircleX, tone: 'danger', text: item.reason ?? 'not on Spotify any more', pill: { label: 'Unavailable', tone: 'red' } };
    case 'carried_over':
      // web-ui.md § Queue, Carried over: cut off when the window ended; it runs first next time.
      return { icon: CircleArrowRight, tone: 'sub', text: `${item.counts.recorded} recorded`, pill: { label: 'Carried over', tone: 'blue' } };
    case 'stopped':
      return { icon: CircleSlash, tone: 'sub', text: `${item.counts.recorded} recorded`, pill: { label: 'Stopped', tone: 'neutral' } };
    default:
      return { icon: CircleMinus, tone: 'sub', text: countsText(item) };
  }
}

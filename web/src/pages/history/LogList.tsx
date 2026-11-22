// The Logs tab's lines (xRi3r): a black box of monospace lines, each with its time, a source badge
// and its message in its level's colour. web-ui.md § Logs tab:
// - The view follows the bottom as lines come. Scrolling up pauses it, and "Jump to latest" shows.
// - Near the top, the page before loads. "Load older lines" does the same: a pill at the top of
//   the box, outside the scroller, so focusing it never scrolls the lines (nor pauses the tail).
//   It shows when the lines are scrolled to the top, when there are none, or when it has keyboard
//   focus; it stays focusable while it loads (aria-disabled, not disabled).
// - A row marks each new day, and the first day if it isn't today (the drawing shows one day).
// - Under about 560 px wide, a row puts its time and badge on one line and the message under them.
// The scroll position stays on the same line when lines are added above or dropped below: the
// first line in view is the anchor.

import { memo, useLayoutEffect, useMemo, useRef, type UIEvent } from 'react';
import { ArrowDown } from 'lucide-react';
import type { LogLine } from '@/api';
import { cx } from '@/lib/cx.ts';
import { formatDay } from '@/shell';
import { dayKey, levelWord, logMoment, logTime, SOURCE_BADGE } from './log-words.ts';
import type { LogView } from './use-log-view.ts';
import styles from './LogList.module.css';

/** Within this many px of the bottom counts as at the bottom: following. */
const BOTTOM_PX = 24;
/** Within this many px of the top, the page before loads. */
const TOP_PX = 160;
/** Within this many px of the top, "Load older lines" shows (in the room left for it above the lines). */
const PILL_PX = 8;

interface Anchor {
  id: string;
  /** The line's top, from the scroller's top edge. */
  offset: number;
}

export function LogList({ view, empty }: { view: LogView; empty: string }) {
  const panel = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const anchor = useRef<Anchor | null>(null);
  /** "Load older lines" was pressed: if it goes (no older lines left) while it has focus, the log takes it. */
  const olderPressed = useRef(false);
  const { lines, following, older } = view;

  // After each change: at the bottom while following, else on the line that was in view.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (following) {
      el.scrollTop = el.scrollHeight;
    } else if (anchor.current) {
      // Ids are digits, letters, dots, dashes and underscores: safe in a selector as they are.
      const row = el.querySelector<HTMLElement>(`[data-line-id="${anchor.current.id}"]`);
      if (row) el.scrollTop = row.offsetTop - anchor.current.offset;
    }
    anchor.current = firstInView(el);
    markTop(panel.current, el);
  }, [lines, following, older]);

  // "Load older lines" went away under the keyboard's focus: keep the focus in the log.
  useLayoutEffect(() => {
    if (older !== null || !olderPressed.current) return;
    olderPressed.current = false;
    if (!document.activeElement || document.activeElement === document.body) scroller.current?.focus({ preventScroll: true });
  }, [older]);

  function onScroll(event: UIEvent<HTMLDivElement>) {
    const el = event.currentTarget;
    anchor.current = firstInView(el);
    markTop(panel.current, el);
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < BOTTOM_PX;
    if (atBottom && !following) view.follow();
    else if (!atBottom && following && el.scrollHeight > el.clientHeight) view.pause();
    if (el.scrollTop < TOP_PX && older !== null) view.loadOlder();
  }

  function onOlder() {
    if (view.loadingOlder) return;
    olderPressed.current = true;
    view.loadOlder();
  }

  // Leaving "Jump to latest" (it goes once the view follows) for the log, so the keyboard's focus stays there.
  function onJump() {
    scroller.current?.focus({ preventScroll: true });
    view.jumpToLatest();
  }

  const days = useMemo(() => dayRows(lines), [lines]);

  return (
    <div ref={panel} className={styles.panel} data-empty={lines.length === 0 || undefined}>
      {older !== null ? (
        <button
          type="button"
          className={styles.older}
          onClick={onOlder}
          aria-disabled={view.loadingOlder || undefined}
          aria-busy={view.loadingOlder || undefined}
          data-loading={view.loadingOlder || undefined}
        >
          {view.loadingOlder ? 'Loading older lines…' : 'Load older lines'}
        </button>
      ) : null}
      <div
        ref={scroller}
        className={cx(styles.scroller, older !== null && styles.roomAbove)}
        role="log"
        aria-live="off"
        aria-label="Log lines"
        tabIndex={0}
        onScroll={onScroll}
      >
        {lines.length === 0 ? <p className={styles.empty}>{empty}</p> : null}
        {lines.map((line, i) => (
          <LogRowWithDay key={line.id} line={line} day={days[i] ?? null} />
        ))}
      </div>
      {!following && lines.length > 0 ? (
        <button type="button" className={styles.jump} onClick={onJump}>
          <ArrowDown size={16} aria-hidden />
          Jump to latest
          {view.pending.length > 0 ? (
            <span className="visually-hidden">
              {' '}
              ({view.pending.length} new {view.pending.length === 1 ? 'line' : 'lines'})
            </span>
          ) : null}
        </button>
      ) : null}
    </div>
  );
}

/** Marks the panel while its lines are scrolled to the top, where "Load older lines" shows. */
function markTop(panel: HTMLElement | null, el: HTMLElement) {
  if (panel) panel.dataset.atTop = el.scrollTop < PILL_PX ? 'true' : 'false';
}

/** For each line, the day's name when it starts a day: a new day, or the first line's when it isn't today. */
function dayRows(lines: readonly LogLine[]): (string | null)[] {
  let last = dayKey(new Date().toISOString());
  return lines.map((line) => {
    const day = dayKey(line.at);
    const starts = day !== last;
    last = day;
    return starts ? formatDay(line.at) : null;
  });
}

/** The first line whose bottom is below the scroller's top: what the reader is looking at. */
function firstInView(el: HTMLElement): Anchor | null {
  const rows = el.querySelectorAll<HTMLElement>('[data-line-id]');
  let low = 0;
  let high = rows.length - 1;
  let found: HTMLElement | null = null;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const row = rows[mid];
    if (!row) break;
    if (row.offsetTop + row.offsetHeight > el.scrollTop) {
      found = row;
      high = mid - 1;
    } else {
      low = mid + 1;
    }
  }
  if (!found) return null;
  return { id: found.dataset.lineId ?? '', offset: found.offsetTop - el.scrollTop };
}

const LogRowWithDay = memo(function LogRowWithDay({ line, day }: { line: LogLine; day: string | null }) {
  return (
    <>
      {day ? <p className={styles.day}>{day}</p> : null}
      <LogRow line={line} />
    </>
  );
});

const LogRow = memo(function LogRow({ line }: { line: LogLine }) {
  const level = levelWord(line.level, line.message);
  return (
    <div className={cx(styles.row, styles[line.level])} data-line-id={line.id} data-level={line.level} data-source={line.source}>
      <time className={styles.time} dateTime={line.at} title={logMoment(line.at)}>
        {logTime(line.at)}
      </time>
      <span className={cx(styles.badge, styles[line.source])} title={line.service}>
        {SOURCE_BADGE[line.source]}
        {/* Which service wrote a System line (xserver, pulseaudio, ...), or which item log a Spytify line is in. */}
        {line.source === 'system' || line.source === 'spytify' ? <span className="visually-hidden">, {line.service}</span> : null}
      </span>
      <span className={styles.message}>
        {level ? <span className="visually-hidden">{level}</span> : null}
        {line.message}
      </span>
    </div>
  );
});

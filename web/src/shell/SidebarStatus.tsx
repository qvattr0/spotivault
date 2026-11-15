import { Unplug } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import { useQueue, useSocketState, useSpotifyConnection, useStatus } from '@/state';
import { connectionLine, statusLine } from './run-words.ts';
import { useNow } from './use-now.ts';
import { useScheduleNext } from './use-schedule-next.ts';
import styles from './SidebarStatus.module.css';

/**
 * The status card at the bottom of the sidebar (components.md § Sidebar › Status card): the live
 * run state, or the next backup, then the Spotify connection. Its first line is the shell's status
 * line. `data-run-state` and `data-socket` are for tests.
 */
export function SidebarStatus() {
  const status = useStatus();
  const queue = useQueue();
  const connection = useSpotifyConnection();
  const socket = useSocketState();
  const next = useScheduleNext();
  // "tonight 01:00" turns into "today 01:00" at midnight.
  const now = useNow(60_000);

  const line = statusLine(status, queue, next, now);
  const conn = connectionLine(connection);
  const Icon = line.icon;

  return (
    <div className={styles.card} data-testid="run-state" data-run-state={status?.state ?? 'unknown'} data-socket={socket}>
      {/* Not drawn: the controller can't be reached. What's shown is the last known state. */}
      {socket === 'reconnecting' && (
        <p className={cx(styles.line, styles.warn)} role="alert">
          <Unplug size={14} />
          Reconnecting to spotivault…
        </p>
      )}
      <p className={cx(styles.line, styles[line.tone])} role="status">
        <Icon size={14} />
        {line.text}
      </p>
      {conn && (
        <p className={styles.connection}>
          <span className={cx(styles.dot, styles[conn.tone])} />
          {conn.text}
        </p>
      )}
    </div>
  );
}

import { useEffect, useId } from 'react';
import { CircleAlert, Play } from 'lucide-react';
import { api, useApi } from '@/api';
import { Button, ButtonLink } from '@/components/ui-a';
import { cx } from '@/lib/cx.ts';
import { errorText } from '@/lib/errors.ts';
import { useAction } from '@/lib/use-action.ts';
import { useNow } from '@/shell';
import type { EventType } from '@/state';
import { WeekStrip } from './WeekStrip.tsx';
import { coverageText, heldWords, nextBackupTitle } from './words.ts';
import styles from './Dashboard.module.css';

/** What changes the next backup: a run ending, the connection or the client's login (Held). */
const RELOAD_ON: EventType[] = ['run.finished', 'connection', 'client.status'];
/** A window can open or pass with no event, so it's read again this often anyway. */
const REFRESH_MS = 5 * 60_000;

/**
 * The Next backup card (web-ui.md § Idle, card 1): when the next run is, what it covers, and Run
 * now. Variants: no schedule, and Held (red, with Reconnect or Log in again in Run now's place).
 * Not in M1: "Change schedule" (the Schedule page comes later), so it isn't shown.
 */
export function NextBackupCard() {
  const titleId = useId();
  const next = useApi((signal) => api.GET('/api/schedule/next', { signal }), [], { reloadOn: RELOAD_ON });
  const { reload } = next;
  useEffect(() => {
    const id = setInterval(reload, REFRESH_MS);
    return () => clearInterval(id);
  }, [reload]);
  // "in 9 h" moves on with the clock.
  const now = useNow(30_000);
  // The page switches to the running Dashboard by itself once the run starts (run.state).
  const runNow = useAction(() => api.POST('/api/runs', { body: {} }));

  const data = next.data;
  const held = data ? heldWords(data.held_reason) : null;

  let title: string;
  let sub: string;
  if (held) {
    title = 'Backups held';
    sub = held.text;
  } else if (data) {
    title = nextBackupTitle(data, now);
    sub = coverageText(data);
  } else if (next.error) {
    title = 'Next backup unknown';
    sub = errorText(next.error);
  } else {
    title = '';
    sub = 'Loading…';
  }

  return (
    <section className={cx(styles.card, styles.nextCard, held && styles.held)} aria-labelledby={titleId}>
      <div className={styles.nextMain}>
        <h2 id={titleId} className={styles.label}>
          Next backup
        </h2>
        <div className={styles.nextText}>
          <p className={styles.nextTitle}>
            {held && <CircleAlert size={32} aria-hidden className={styles.heldIcon} />}
            {title}
          </p>
          <p className={styles.nextSub}>{sub}</p>
        </div>
        <div className={styles.nextActions}>
          {held ? (
            <ButtonLink variant="primary" to={held.action.to}>
              {held.action.label}
            </ButtonLink>
          ) : (
            <Button variant="primary" icon={Play} busy={runNow.busy} onClick={() => void runNow.run()}>
              Run now
            </Button>
          )}
        </div>
      </div>
      {data?.at ? <WeekStrip /> : null}
    </section>
  );
}

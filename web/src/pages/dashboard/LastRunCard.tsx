import { useId } from 'react';
import { ChevronRight, CircleAlert, CircleCheck, CircleX, HardDrive, Redo2, type LucideIcon } from 'lucide-react';
import { api, useApi, type Counters } from '@/api';
import { ButtonLink } from '@/components/ui-a';
import { OutcomePill } from '@/components/ui-c';
import { cx } from '@/lib/cx.ts';
import { errorText } from '@/lib/errors.ts';
import { failureText } from '@/lib/run-words.ts';
import { formatBytes, formatCount } from '@/shell';
import { lastRunTitle } from './words.ts';
import styles from './Dashboard.module.css';

/**
 * The Last run card (web-ui.md § Idle, card 3; fzNDm): when, the outcome, the counters, up to three
 * items with problems, and a link to the run in History. Before the first run: "No backups yet".
 */
export function LastRunCard() {
  const titleId = useId();
  const last = useApi((signal) => api.GET('/api/runs/last', { signal }), [], { reloadOn: ['run.finished'] });
  const run = last.data?.run ?? null;
  const issues = last.data?.issues ?? [];

  return (
    <section className={styles.card} aria-labelledby={titleId}>
      <div className={styles.lastHead}>
        <div className={styles.lastTitles}>
          <h2 id={titleId} className={styles.label}>
            Last run
          </h2>
          {run ? (
            <p className={styles.lastTitle}>{lastRunTitle(run)}</p>
          ) : last.data ? (
            <p className={styles.lastTitle}>No backups yet</p>
          ) : last.error ? (
            <p className={styles.muted}>{errorText(last.error)}</p>
          ) : null}
          {run?.outcome === 'failed' && run.reason ? <p className={styles.muted}>Failed: {failureText(run.reason)}</p> : null}
        </div>
        {run?.outcome ? <OutcomePill outcome={run.outcome} /> : null}
      </div>

      {run?.counters ? <Stats counters={run.counters} /> : null}

      {issues.length > 0 ? (
        <div className={styles.issues}>
          <h3 className={styles.label}>Issues</h3>
          <ul className={styles.issueList}>
            {issues.map((issue) => (
              <li key={issue.item_id} className={styles.issue}>
                <CircleAlert size={16} aria-hidden className={styles.issueIcon} />
                {issue.name}: {issue.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {run ? (
        <div>
          <ButtonLink variant="tertiary" trailingIcon={ChevronRight} to={`/history/runs/${run.id}`}>
            View in History
          </ButtonLink>
        </div>
      ) : null}
    </section>
  );
}

/** The four counters (fzNDm): recorded · skipped (duplicate) · failed, and the size added. */
function Stats({ counters }: { counters: Counters }) {
  return (
    <dl className={styles.stats}>
      <Stat icon={CircleCheck} tone="accent" label="recorded" value={formatCount(counters.recorded)} />
      <Stat icon={Redo2} label="skipped (duplicate)" value={formatCount(counters.skipped_duplicate)} />
      <Stat icon={CircleX} tone="danger" label="failed" value={formatCount(counters.failed)} />
      <Stat icon={HardDrive} label="added" value={`+${formatBytes(counters.bytes_added)}`} />
    </dl>
  );
}

function Stat({ icon: Icon, tone, label, value }: { icon: LucideIcon; tone?: 'accent' | 'danger'; label: string; value: string }) {
  return (
    <div className={styles.stat}>
      <dt className={styles.statLabel}>
        <Icon size={14} aria-hidden className={cx(tone && styles[tone])} />
        {label}
      </dt>
      <dd className={styles.statValue}>{value}</dd>
    </div>
  );
}

import { PageHeader } from '@/shell';
import { LastRunCard } from './LastRunCard.tsx';
import { NextBackupCard } from './NextBackupCard.tsx';
import styles from './Dashboard.module.css';

/**
 * The Dashboard when no run is going (web-ui.md § Idle, fzNDm): Next backup, then Last run.
 * Not yet (plan D8): the Full backup card between them waits for the user's review.
 */
export function IdleDashboard() {
  return (
    <>
      <PageHeader title="Dashboard" />
      <div className={styles.cards}>
        <NextBackupCard />
        <LastRunCard />
      </div>
    </>
  );
}

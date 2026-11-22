import { PageHeader } from '@/shell';
import { FullBackupCard } from './FullBackupCard.tsx';
import { LastRunCard } from './LastRunCard.tsx';
import { NextBackupCard } from './NextBackupCard.tsx';
import styles from './Dashboard.module.css';

/**
 * The Dashboard when no run is going (web-ui.md § Idle, fzNDm): Next backup, Full backup, then
 * Last run. The Full backup card isn't drawn: it's built from web-ui.md (plan D8).
 */
export function IdleDashboard() {
  return (
    <>
      <PageHeader title="Dashboard" />
      <div className={styles.cards}>
        <NextBackupCard />
        <FullBackupCard />
        <LastRunCard />
      </div>
    </>
  );
}

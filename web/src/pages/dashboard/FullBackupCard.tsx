import { useId } from 'react';
import { ChevronRight, CircleCheck } from 'lucide-react';
import type { Backlog } from '@/api';
import { ButtonLink } from '@/components/ui-a';
import { Progress } from '@/components/ui-b';
import {
  backlogPercent,
  backlogState,
  completeLine,
  finishLine,
  knownDoneLine,
  measuringLine,
  timeLeftLine,
  tracksLine,
  unknownLine,
  unknownOnlyLine,
  updatedLine,
} from '@/lib/backlog-words.ts';
import { errorText } from '@/lib/errors.ts';
import { useBacklogEstimate } from '@/lib/use-backlog-estimate.ts';
import { useNow } from '@/shell';
import styles from './Dashboard.module.css';

/**
 * The Full backup card (web-ui.md § Idle, card 2): how far the backup of everything tracked has
 * got, and how long the rest takes, from the backlog estimate. Not drawn: built from the spec and
 * the mockup the user approved (plan D8). States in backlogState (lib/backlog-words.ts):
 * - In progress: the bar (recorded time out of total time), "4,708 of 5,120 tracks · 87% of the
 *   music", "About 27 h of recording left", the finish, the unknown and still-measuring lines.
 * - Complete: a green check and "Everything is backed up · 298 h of music".
 * - Measuring: a skeleton bar and line, and "Measuring your library…".
 * - Ours: everything of known length recorded, only playlists of unknown length, nothing tracked.
 */
export function FullBackupCard() {
  const titleId = useId();
  const { backlog, error } = useBacklogEstimate();
  // "Updated 01:00" gains its day once it isn't today.
  const now = useNow(60_000);

  return (
    <section className={styles.card} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.label}>
        Full backup
      </h2>
      {backlog ? (
        <Estimate backlog={backlog} now={now} />
      ) : error ? (
        <p className={styles.muted}>{errorText(error)}</p>
      ) : (
        <Measuring />
      )}
    </section>
  );
}

function Estimate({ backlog, now }: { backlog: Backlog; now: number }) {
  const updated = <p className={styles.quiet}>{updatedLine(backlog.as_of, now)}</p>;
  const notes = [unknownLine(backlog), measuringLine(backlog)].filter((line): line is string => line !== null);

  switch (backlogState(backlog)) {
    case 'measuring':
      return <Measuring />;

    case 'in_progress':
      return (
        <div className={styles.backup}>
          <div className={styles.backupBar}>
            {/* The bar shows the same rounded-down percent as the line, so a screen reader never
                hears 100 % (or 90.9 % next to "90 %") before everything is recorded. */}
            <Progress value={backlogPercent(backlog) / 100} label="Full backup" />
            <p className={styles.muted}>{tracksLine(backlog)}</p>
          </div>
          <div className={styles.backupText}>
            <p className={styles.backupTitle}>{timeLeftLine(backlog)}</p>
            <p className={styles.muted}>{finishLine(backlog)}</p>
            {notes.map((note) => (
              <p key={note} className={styles.muted}>
                {note}
              </p>
            ))}
          </div>
          {updated}
        </div>
      );

    case 'complete':
      return (
        <div className={styles.backup}>
          <p className={styles.backupTitle}>
            <CircleCheck size={24} aria-hidden className={styles.accent} />
            {completeLine(backlog)}
          </p>
          {updated}
        </div>
      );

    case 'known_done':
      return (
        <div className={styles.backup}>
          <div className={styles.backupText}>
            <p className={styles.backupTitle}>{knownDoneLine(backlog)}</p>
            {notes.map((note) => (
              <p key={note} className={styles.muted}>
                {note}
              </p>
            ))}
          </div>
          {updated}
        </div>
      );

    case 'unknown_only':
      return (
        <div className={styles.backup}>
          <p className={styles.backupTitle}>{unknownOnlyLine(backlog)}</p>
          {updated}
        </div>
      );

    case 'empty':
      return (
        <div className={styles.backup}>
          <div className={styles.backupText}>
            <p className={styles.backupTitle}>Nothing to back up yet</p>
            <p className={styles.muted}>Track playlists in the Library, or add albums on the Albums page.</p>
          </div>
          <div className={styles.backupLinks}>
            <ButtonLink variant="tertiary" trailingIcon={ChevronRight} to="/library">
              Open Library
            </ButtonLink>
            <ButtonLink variant="tertiary" trailingIcon={ChevronRight} to="/albums">
              Open Albums
            </ButtonLink>
          </div>
        </div>
      );
  }
}

/**
 * Measuring (web-ui.md § Idle, Variants): a skeleton bar and line, then "Measuring your library…".
 * The skeleton is marked busy; its text stays readable (the shapes alone are hidden).
 */
function Measuring() {
  return (
    <div className={styles.backup} aria-busy="true">
      <div className={styles.backupBar} aria-hidden>
        <div className={styles.skeletonBar} />
        <div className={styles.skeletonLine} />
      </div>
      <p className={styles.muted}>Measuring your library…</p>
    </div>
  );
}

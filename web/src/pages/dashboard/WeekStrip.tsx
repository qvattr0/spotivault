import { api, useApi, type Hours } from '@/api';
import { cx } from '@/lib/cx.ts';
import styles from './Dashboard.module.css';

const DAYS: { key: keyof Hours; letter: string }[] = [
  { key: 'mon', letter: 'M' },
  { key: 'tue', letter: 'T' },
  { key: 'wed', letter: 'W' },
  { key: 'thu', letter: 'T' },
  { key: 'fri', letter: 'F' },
  { key: 'sat', letter: 'S' },
  { key: 'sun', letter: 'S' },
];
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

/**
 * The small week strip on the Next backup card (fzNDm): a row per day, a cell per hour, the
 * backup hours in green. Drawn, though web-ui.md doesn't mention it; it only shows the schedule
 * (GET /api/schedule), and links nowhere, since the Schedule page isn't in M1.
 */
export function WeekStrip() {
  const schedule = useApi((signal) => api.GET('/api/schedule', { signal }), []);
  const data = schedule.data;
  if (!data) return null;
  const hours = data.hours;
  if (DAYS.every((day) => hours[day.key].length === 0)) return null;

  return (
    <div className={styles.week} role="img" aria-label={`Backup hours: ${data.hours_per_week} h a week`}>
      {DAYS.map((day) => (
        <div key={day.key} className={styles.weekRow}>
          <span className={styles.weekDay}>{day.letter}</span>
          {HOURS.map((hour) => (
            <span key={hour} className={cx(styles.weekCell, hours[day.key].includes(hour) && styles.weekOn)} />
          ))}
        </div>
      ))}
    </div>
  );
}

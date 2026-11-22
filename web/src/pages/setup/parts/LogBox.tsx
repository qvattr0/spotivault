import { cx } from '@/lib/cx.ts';
import styles from './Step.module.css';

interface LogBoxProps {
  /** The lines, oldest first. Only the last `max` show. */
  lines: readonly string[];
  /** How many lines to show. */
  max?: number;
  /** Draw the last line in red: the line that failed (dxPUp). */
  lastIsError?: boolean;
  label: string;
}

/** The install's last log lines, in the black mono box (h2Qgw, dxPUp). */
export function LogBox({ lines, max = 6, lastIsError = false, label }: LogBoxProps) {
  if (lines.length === 0) return null;
  const shown = lines.slice(-max);
  return (
    <div className={cx(styles.monoBox, styles.log)} role="log" aria-label={label}>
      {shown.map((line, i) => (
        // Lines can repeat, so their place in the list is part of the key.
        <p key={`${i}-${line}`} className={cx(lastIsError && i === shown.length - 1 && styles.errorLine)}>
          {line}
        </p>
      ))}
    </div>
  );
}

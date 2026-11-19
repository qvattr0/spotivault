import { cx } from '@/lib/cx.ts';
import { FLOOR_DBFS, litSegments, SEGMENTS, segmentTone } from './level-scale.ts';
import styles from './LevelMeter.module.css';

export interface LevelMeterProps {
  /** The peak in dBFS, or null for silence. */
  peakDbfs: number | null;
  className?: string;
}

const INDEXES = Array.from({ length: SEGMENTS }, (_, i) => i);

/**
 * `LevelMeter` (components.md § Level meter): 24 segments, green, then yellow at the top.
 * This one only draws a value. During a run use LiveLevelMeter, which reads the live `level` events.
 */
export function LevelMeter({ peakDbfs, className }: LevelMeterProps) {
  const lit = litSegments(peakDbfs);
  const silent = lit === 0;

  return (
    <div
      className={cx(styles.meter, className)}
      role="meter"
      aria-label="Recording level"
      aria-valuemin={FLOOR_DBFS}
      aria-valuemax={0}
      aria-valuenow={silent ? FLOOR_DBFS : Math.min(Math.round(peakDbfs ?? FLOOR_DBFS), 0)}
      aria-valuetext={silent ? 'Silent' : `${Math.round(peakDbfs ?? 0)} dBFS`}
    >
      {INDEXES.map((i) => (
        <span key={i} className={cx(styles.segment, i < lit && styles[segmentTone(i)])} />
      ))}
    </div>
  );
}

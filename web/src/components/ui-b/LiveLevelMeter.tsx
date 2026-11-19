import { useEffect, useState } from 'react';
import { useLevel, type LevelReading } from '@/state';
import { LevelMeter } from './LevelMeter.tsx';

/**
 * How long a reading stays on the meter. The controller sends `level` up to 10 times a second while
 * recording, and none after; the meter then falls to silence on its own (contracts/events.md § Level
 * throttling). 600 ms lets a slow client miss a few readings without the meter flickering.
 */
export const SILENCE_AFTER_MS = 600;

export interface LiveLevelMeterProps {
  className?: string;
}

/**
 * The level meter fed by the live `level` events. Only this component subscribes to them, so the
 * 10 updates a second re-render the meter alone, never the strip or page around it.
 */
export function LiveLevelMeter({ className }: LiveLevelMeterProps) {
  const reading = useLevel();
  // The last reading that went stale with no newer one after it.
  const [stale, setStale] = useState<LevelReading | null>(null);

  useEffect(() => {
    if (!reading) return;
    const timer = setTimeout(() => setStale(reading), SILENCE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [reading]);

  const silent = !reading || reading === stale;
  return <LevelMeter peakDbfs={silent ? null : reading.level.peak_dbfs} className={className} />;
}

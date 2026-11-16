import { useEffect, useState } from 'react';

/**
 * The time, updated every `intervalMs` while `active`. When not active it stops ticking and keeps
 * the last value, which is how the track clock stands still while a run is paused.
 */
export function useNow(intervalMs: number, active = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, active]);
  return now;
}

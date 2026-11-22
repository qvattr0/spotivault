// The level meter's scale. The drawing (components.md § Level meter) has 24 segments but doesn't
// say what level each stands for, or where green turns yellow. Our cautious reading, as on a
// digital audio meter:
// - each segment is 2 dB, so the meter spans -48 dBFS (segment 0) to 0 dBFS;
// - segments from -18 dBFS up (the usual digital reference level) are yellow, which matches the
//   drawing: segments 0-14 green, 15 and up yellow.

export const SEGMENTS = 24;
export const FLOOR_DBFS = -48;
export const STEP_DB = 2;
/** The first yellow segment: it lights at -18 dBFS. */
export const WARN_FROM_SEGMENT = 15;

/** How many segments a peak lights, from 0 (silence) to 24. Segment i lights at FLOOR_DBFS + i × STEP_DB. */
export function litSegments(peakDbfs: number | null): number {
  if (peakDbfs === null || !Number.isFinite(peakDbfs)) return 0;
  const lit = Math.floor((peakDbfs - FLOOR_DBFS) / STEP_DB) + 1;
  return Math.min(Math.max(lit, 0), SEGMENTS);
}

/** The colour of a lit segment. */
export function segmentTone(index: number): 'accent' | 'warn' {
  return index >= WARN_FROM_SEGMENT ? 'warn' : 'accent';
}

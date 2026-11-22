// @vitest-environment node
// The mock's sum of a run's time left against the contract's vectors
// (contracts/vectors/run-time-left.json): the same cases the controller's engine/time_left.py passes.

import { describe, expect, it } from 'vitest';
import vectors from '../../contracts/vectors/run-time-left.json';
import { workOut, type ItemLeft, type MissingTrack } from './time-left.ts';

interface Case {
  id: string;
  input: {
    stop_mode: 'after_track' | 'now' | null;
    current: ItemLeft | null;
    waiting: (MissingTrack[] | null)[];
    recorded: string[];
    window_left_ms: number | null;
  };
  expected: { ms: number; seconds: number; unknown_items: number };
}

describe("a run's time left", () => {
  it.each((vectors.cases as Case[]).map((c) => [c.id, c] as const))('%s', (_, c) => {
    const { current, waiting, stop_mode: stopMode, recorded, window_left_ms: windowMs } = c.input;
    expect(workOut(current, waiting, stopMode, { recorded, windowMs })).toEqual(c.expected);
  });
});

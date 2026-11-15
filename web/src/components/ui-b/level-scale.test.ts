import { describe, expect, it } from 'vitest';
import { litSegments, segmentTone, SEGMENTS } from './level-scale.ts';

describe('litSegments', () => {
  it('lights nothing for silence or no reading', () => {
    expect(litSegments(null)).toBe(0);
    expect(litSegments(-90)).toBe(0);
    expect(litSegments(-Infinity)).toBe(0);
    expect(litSegments(Number.NaN)).toBe(0);
  });

  it('lights one segment per 2 dB from -48 dBFS', () => {
    expect(litSegments(-48)).toBe(1);
    expect(litSegments(-46.5)).toBe(1);
    expect(litSegments(-46)).toBe(2);
    expect(litSegments(-15)).toBe(17); // the drawing: 15 green, 2 yellow
  });

  it('never lights more than the meter has', () => {
    expect(litSegments(-2)).toBe(SEGMENTS);
    expect(litSegments(0)).toBe(SEGMENTS);
    expect(litSegments(3)).toBe(SEGMENTS);
  });
});

describe('segmentTone', () => {
  it('turns yellow from segment 15 (-18 dBFS)', () => {
    expect(segmentTone(14)).toBe('accent');
    expect(segmentTone(15)).toBe('warn');
    expect(segmentTone(23)).toBe('warn');
  });
});

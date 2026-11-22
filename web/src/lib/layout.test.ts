// The layout rules against the contract's vectors (contracts/vectors/layouts.json): the same
// verdict and reason as the controller for every case.

import { describe, expect, it } from 'vitest';
import layouts from '../../../contracts/vectors/layouts.json';
import { checkLayout, DEFAULT_LAYOUT_PATTERN } from './layout.ts';

interface Case {
  id: string;
  layout: { pattern: string };
  expected: { valid: boolean; reason?: string; placeholder?: string | null };
}

const vectors = layouts as { cases: Case[] };

describe('checkLayout', () => {
  it.each(vectors.cases.map((c) => [c.id, c] as const))('%s', (_id, c) => {
    const check = checkLayout(c.layout.pattern);
    expect(check.valid).toBe(c.expected.valid);
    if (!check.valid) {
      expect(check.reason).toBe(c.expected.reason);
      if (c.expected.placeholder !== undefined) expect(check.placeholder).toBe(c.expected.placeholder);
    }
  });

  it('accepts the default', () => {
    expect(checkLayout(DEFAULT_LAYOUT_PATTERN)).toEqual({ valid: true });
  });
});

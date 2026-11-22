import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SEARCH_DELAY_MS, useDebouncedValue } from './list-query.ts';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useDebouncedValue', () => {
  it('passes a value on once it has stayed the same for the delay', () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, SEARCH_DELAY_MS), { initialProps: { value: '' } });
    rerender({ value: 'ro' });
    rerender({ value: 'rock' });
    expect(result.current).toBe('');
    act(() => vi.advanceTimersByTime(SEARCH_DELAY_MS));
    expect(result.current).toBe('rock');
  });

  it('clears at once, and a key pressed right after never brings the old search back', () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, SEARCH_DELAY_MS), { initialProps: { value: 'rock' } });
    expect(result.current).toBe('rock');
    rerender({ value: '' });
    expect(result.current).toBe('');
    // Typed within the delay after the clear.
    act(() => vi.advanceTimersByTime(50));
    rerender({ value: 'j' });
    expect(result.current).toBe('');
    act(() => vi.advanceTimersByTime(SEARCH_DELAY_MS));
    expect(result.current).toBe('j');
  });
});

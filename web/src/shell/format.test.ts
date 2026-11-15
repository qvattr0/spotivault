import { describe, expect, it } from 'vitest';
import { formatDate, formatDuration, formatWhen } from './format.ts';

// Built from local times, so the tests pass in any time zone.
const at = (day: number, hour: number, minute = 0) => new Date(2026, 10, day, hour, minute).toISOString();
const now = (day: number, hour: number) => new Date(2026, 10, day, hour).getTime();

describe('formatDate', () => {
  it('writes the day, the short month and the year', () => {
    expect(formatDate(new Date(2027, 4, 12, 20).toISOString())).toBe('12 May 2027');
  });
});

describe('formatWhen', () => {
  it('calls the coming night "tonight", from the afternoon', () => {
    expect(formatWhen(at(16, 1), now(15, 16))).toBe('tonight 01:00');
    expect(formatWhen(at(15, 22), now(15, 9))).toBe('tonight 22:00');
    expect(formatWhen(at(15, 1), now(15, 0))).toBe('tonight 01:00');
  });

  it('says today, tomorrow, or the date', () => {
    expect(formatWhen(at(15, 14), now(15, 9))).toBe('today 14:00');
    expect(formatWhen(at(16, 1), now(15, 9))).toBe('tomorrow 01:00');
    expect(formatWhen(at(16, 9), now(15, 20))).toBe('tomorrow 09:00');
    expect(formatWhen(at(18, 1), now(15, 20))).toBe('Wed 18 Nov 01:00');
  });
});

describe('formatDuration', () => {
  it('writes minutes and seconds, and hours when there are any', () => {
    expect(formatDuration(161_000)).toBe('2:41');
    expect(formatDuration(383_999)).toBe('6:23');
    expect(formatDuration(3_723_000)).toBe('1:02:03');
    expect(formatDuration(-500)).toBe('0:00');
  });
});

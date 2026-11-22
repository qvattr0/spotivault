import { describe, expect, it } from 'vitest';
import {
  formatAgo,
  formatBytes,
  formatCount,
  formatDate,
  formatDayTime,
  formatDuration,
  formatHours,
  formatLength,
  formatRunLength,
  formatWhen,
} from './format.ts';

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

describe("S8's formats", () => {
  it('writes days, sizes, counts and lengths as the drawings do', () => {
    expect(formatDayTime(at(10, 1))).toBe('Tue 10 Nov 01:00');
    expect(formatBytes(9_400_000)).toBe('9.4 MB');
    expect(formatBytes(412_000_000)).toBe('412 MB');
    expect(formatBytes(1_843_000_000_000)).toBe('1.84 TB');
    expect(formatCount(1204)).toBe('1,204');
    expect(formatRunLength(18_720)).toBe('5 h 12 m');
    expect(formatRunLength(2_280)).toBe('38 m');
    expect(formatRunLength(21_600)).toBe('6 h 00 m');
    expect(formatHours(97_305)).toBe('27 h');
    expect(formatLength(28_080_000)).toBe('7 h 48 min');
  });

  it('says hours of music in whole hours, or minutes under an hour', () => {
    expect(formatHours(0)).toBe('1 min'); // never "0 min" while something is left
    expect(formatHours(35)).toBe('1 min'); // an item's overhead alone
    expect(formatHours(59 * 60)).toBe('59 min');
    // 59 min 40 s rounds to 60 minutes: that's an hour, not "60 min".
    expect(formatHours(59 * 60 + 40)).toBe('1 h');
    expect(formatHours(60 * 60)).toBe('1 h');
    expect(formatHours(90 * 60)).toBe('2 h'); // half up
    expect(formatHours(1_074_200)).toBe('298 h');
    expect(formatHours(4_500_000)).toBe('1,250 h');
  });

  it('says how long ago, or Never', () => {
    const base = now(15, 12);
    expect(formatAgo(null, base)).toBe('Never');
    expect(formatAgo(new Date(base - 30_000).toISOString(), base)).toBe('just now');
    expect(formatAgo(new Date(base - 3 * 3_600_000).toISOString(), base)).toBe('3 hours ago');
    expect(formatAgo(new Date(base - 2 * 86_400_000).toISOString(), base)).toBe('2 days ago');
    expect(formatAgo(new Date(base - 8 * 86_400_000).toISOString(), base)).toBe('1 week ago');
  });
});

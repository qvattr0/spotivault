import { describe, expect, it } from 'vitest';
import { backlog as sample, backlogComplete, backlogMeasuring } from '@mock/fixtures.ts';
import type { Backlog } from '@/api';
import { formatDayTime, formatTime } from '@/shell';
import {
  backlogPercent,
  backlogProgress,
  backlogState,
  backupLengthRow,
  completeLine,
  finishLine,
  knownDoneLine,
  measuringLine,
  newestBacklog,
  timeLeftLine,
  tracksLine,
  unknownLine,
  unknownOnlyLine,
  updatedLine,
} from './backlog-words.ts';

/** The contract's example (BacklogScheduled): 4,708 of 5,120 tracks, 27 h left, 2 unknown. */
const scheduled: Backlog = { ...sample, finish_at: '2026-11-16T03:21:45+01:00', as_of: '2026-11-15T00:00:00Z' };
const zero: Backlog = { ...backlogMeasuring, unknown_items: 0, items_measuring: 0 };

describe('backlogState', () => {
  it('is Measuring with no estimate, or while nothing is measured yet', () => {
    expect(backlogState(null)).toBe('measuring');
    expect(backlogState({ ...zero, items_measuring: 3 })).toBe('measuring');
    // Unknown playlists don't stop it measuring the rest.
    expect(backlogState({ ...zero, items_measuring: 3, unknown_items: 2 })).toBe('measuring');
  });

  it('is In progress while something of known length is left, even with some still measuring', () => {
    expect(backlogState(scheduled)).toBe('in_progress');
    expect(backlogState({ ...scheduled, items_measuring: 1 })).toBe('in_progress');
  });

  it('is Complete only with nothing left, nothing unknown and nothing measuring', () => {
    expect(backlogState(backlogComplete)).toBe('complete');
    expect(backlogState({ ...backlogComplete, unknown_items: 2 })).toBe('known_done');
    expect(backlogState({ ...backlogComplete, items_measuring: 1 })).toBe('known_done');
  });

  it('tells nothing tracked from only playlists of unknown length', () => {
    expect(backlogState(zero)).toBe('empty');
    expect(backlogState({ ...zero, unknown_items: 2 })).toBe('unknown_only');
  });
});

describe('newestBacklog', () => {
  const older = { ...scheduled, as_of: '2026-11-15T00:00:00Z' };
  const newer = { ...scheduled, tracks_recorded: 4800, as_of: '2026-11-15T00:10:00Z' };

  it('takes the newer by as_of, whichever source it came from', () => {
    expect(newestBacklog(older, newer)).toBe(newer);
    expect(newestBacklog(newer, older)).toBe(newer);
  });

  it('takes the live one on a tie, and either when the other is missing', () => {
    const same = { ...older };
    expect(newestBacklog(older, same)).toBe(older);
    expect(newestBacklog(null, older)).toBe(older);
    expect(newestBacklog(older, null)).toBe(older);
    expect(newestBacklog(null, null)).toBeNull();
  });
});

describe('the Full backup card words', () => {
  it('says tracks, and the share of the music, under the bar', () => {
    // 975,600 of 1,072,800 s is 90.9 %: the bar is time, the line counts tracks.
    expect(backlogProgress(scheduled)).toBeCloseTo(0.909, 3);
    expect(tracksLine(scheduled)).toBe('4,708 of 5,120 tracks · 90% of the music');
    expect(tracksLine({ ...scheduled, seconds_recorded: 933_336 })).toBe('4,708 of 5,120 tracks · 87% of the music');
    expect(tracksLine({ ...scheduled, tracks_total: 1, tracks_recorded: 0, seconds_recorded: 0, seconds_total: 200 })).toBe(
      '0 of 1 track · 0% of the music',
    );
  });

  it('rounds the percent down, and never says 100 until every track is recorded', () => {
    expect(backlogPercent({ ...scheduled, seconds_recorded: 1_072_799 })).toBe(99);
    // Half a second left can round the seconds up to the total: still 99 %.
    expect(backlogPercent({ ...scheduled, seconds_recorded: 1_072_800, tracks_recorded: 5119 })).toBe(99);
    expect(backlogPercent(backlogComplete)).toBe(100);
    expect(backlogPercent({ ...zero, tracks_total: 3 })).toBe(0);
  });

  it('says the time left in hours, or minutes under an hour', () => {
    expect(timeLeftLine({ seconds_left: 97_305 })).toBe('About 27 h of recording left');
    expect(timeLeftLine({ seconds_left: 2_400 })).toBe('About 40 min of recording left');
    expect(timeLeftLine({ seconds_left: 1_074_200 })).toBe('About 298 h of recording left');
    // Nearly an hour reads as an hour, and one item's 35 s overhead as a minute.
    expect(timeLeftLine({ seconds_left: 3_580 })).toBe('About 1 h of recording left');
    expect(timeLeftLine({ seconds_left: 35 })).toBe('About 1 min of recording left');
  });

  it('says when it will be done, or how to start with Manual only', () => {
    expect(finishLine({ finish_at: '2026-11-16T12:00:00Z' })).toBe('Done around Mon 16 Nov at this schedule');
    expect(finishLine({ finish_at: null })).toBe('Run now to start; recording is real time');
  });

  it('counts the unknown and the still-measuring items, singular and plural', () => {
    expect(unknownLine({ unknown_items: 2 })).toBe('+ 2 followed playlists (unknown length)');
    expect(unknownLine({ unknown_items: 1 })).toBe('+ 1 followed playlist (unknown length)');
    expect(unknownLine({ unknown_items: 0 })).toBeNull();
    expect(measuringLine({ items_measuring: 1 })).toBe('+ 1 playlist or album still being measured');
    expect(measuringLine({ items_measuring: 1_204 })).toBe('+ 1,204 playlists or albums still being measured');
    expect(measuringLine({ items_measuring: 0 })).toBeNull();
    expect(unknownOnlyLine({ unknown_items: 1 })).toBe('1 followed playlist (unknown length)');
  });

  it('says Complete, or everything of known length, with the hours of music', () => {
    expect(completeLine(backlogComplete)).toBe('Everything is backed up · 298 h of music');
    expect(knownDoneLine(backlogComplete)).toBe('Everything of known length is backed up · 298 h of music');
    expect(completeLine({ seconds_total: 2_700 })).toBe('Everything is backed up · 45 min of music');
  });

  it('says when it was updated: the time today, with the day before that', () => {
    const asOf = new Date();
    asOf.setHours(1, 0, 0, 0);
    const now = new Date(asOf);
    now.setHours(9);
    expect(updatedLine(asOf.toISOString(), now.getTime())).toBe(`Updated ${formatTime(asOf.toISOString())}`);
    expect(updatedLine(asOf.toISOString(), now.getTime())).toBe('Updated 01:00');
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);
    expect(updatedLine(asOf.toISOString(), tomorrow.getTime())).toBe(`Updated ${formatDayTime(asOf.toISOString())}`);
  });
});

describe("step 9's Backup length row", () => {
  it('says how much music there is to record, with the unknown ones under it', () => {
    const fresh = { ...scheduled, tracks_recorded: 0, seconds_recorded: 0, seconds_left: 1_074_200 };
    expect(backupLengthRow(fresh)).toEqual({
      value: 'About 298 h of music to record',
      notes: ['+ 2 followed playlists (unknown length)'],
    });
    expect(backupLengthRow({ ...fresh, unknown_items: 0, items_measuring: 2 })).toEqual({
      value: 'About 298 h of music to record',
      notes: ['+ 2 playlists or albums still being measured'],
    });
  });

  it('says Measuring… while the track lists load', () => {
    expect(backupLengthRow(null)).toEqual({ value: 'Measuring…', notes: [] });
    expect(backupLengthRow(backlogMeasuring)).toEqual({ value: 'Measuring…', notes: [] });
  });

  it('says what is left in the other cases', () => {
    expect(backupLengthRow(backlogComplete).value).toBe('Everything is backed up');
    expect(backupLengthRow({ ...backlogComplete, unknown_items: 1 })).toEqual({
      value: 'Everything of known length is backed up',
      notes: ['+ 1 followed playlist (unknown length)'],
    });
    expect(backupLengthRow({ ...zero, unknown_items: 2 }).value).toBe('2 followed playlists (unknown length)');
    expect(backupLengthRow(zero).value).toBe('Nothing to back up yet');
  });
});

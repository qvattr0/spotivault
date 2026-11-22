// History › Logs in words (web-ui.md § Logs tab): the filter chips, the source badges and the
// times. The badges say "Client" where the chip says "Spotify client", as drawn (xRi3r).

import type { LogLevel, LogSource } from '@/api';

export const SOURCE_CHIPS: { value: LogSource; label: string }[] = [
  { value: 'controller', label: 'Controller' },
  { value: 'spytify', label: 'Spytify' },
  { value: 'client', label: 'Spotify client' },
  { value: 'system', label: 'System' },
];

/** The Level chips. Debug lines show only when asked for, and no chip asks (a cautious choice). */
export const LEVEL_CHIPS: { value: LogLevel; label: string }[] = [
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'error', label: 'Error' },
];

export const SOURCE_BADGE: Record<LogSource, string> = {
  controller: 'Controller',
  spytify: 'Spytify',
  client: 'Client',
  system: 'System',
};

/** For screen readers: the level a line's colour shows. Info says nothing. */
export const LEVEL_WORD: Record<LogLevel, string> = {
  debug: 'Debug: ',
  info: '',
  warning: 'Warning: ',
  error: 'Error: ',
};

/** A message that starts with its level's word already says it ("Warning: no GPU found"). */
const SAYS_LEVEL: Record<LogLevel, RegExp | null> = {
  debug: /^\s*debug\b/i,
  info: null,
  warning: /^\s*warn(ing)?\b/i,
  error: /^\s*(error|err|fatal|critical)\b/i,
};

/** The level word screen readers hear before a message: LEVEL_WORD, unless the message starts with it. */
export function levelWord(level: LogLevel, message: string): string {
  const word = LEVEL_WORD[level];
  return word && !SAYS_LEVEL[level]?.test(message) ? word : '';
}

const CLOCK = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
const FULL = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

/** "01:07:11", in the browser's time zone. */
export function logTime(iso: string): string {
  return CLOCK.format(new Date(iso));
}

/** "Tue, 12 Nov 2026, 01:07:11": the time's tooltip, with the milliseconds. */
export function logMoment(iso: string): string {
  const at = new Date(iso);
  return `${FULL.format(at)}.${String(at.getMilliseconds()).padStart(3, '0')}`;
}

/** The local day a time is on, as a key: "2026-11-12". */
export function dayKey(iso: string): string {
  const at = new Date(iso);
  return `${at.getFullYear()}-${at.getMonth() + 1}-${at.getDate()}`;
}

/** The name of the file the browser saves: "spotivault-logs-20261115-0142.zip". */
export function zipName(now: Date): string {
  const two = (n: number) => String(n).padStart(2, '0');
  return `spotivault-logs-${now.getFullYear()}${two(now.getMonth() + 1)}${two(now.getDate())}-${two(now.getHours())}${two(now.getMinutes())}.zip`;
}

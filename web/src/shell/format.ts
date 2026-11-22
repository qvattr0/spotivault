// Dates, times and lengths, written as web-ui.md writes them: "12 May 2027", "tonight 01:00", "2:41".
// Times are in the browser's time zone. The schedule's own zone (TZ in the Docker app) is the same
// on a home LAN; web-ui.md doesn't say which one the UI should use.

const DATE = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
const TIME = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** "12 May 2027" */
export function formatDate(iso: string): string {
  return DATE.format(new Date(iso));
}

/** "01:00" */
export function formatTime(iso: string): string {
  return TIME.format(new Date(iso));
}

/**
 * When something happens, seen from `now`: "tonight 01:00", "today 14:00", "tomorrow 09:00" or
 * "Wed 18 Nov 01:00". The early hours count as tonight from the afternoon before.
 */
export function formatWhen(iso: string, now: number): string {
  const at = new Date(iso);
  const today = new Date(now);
  const days = dayNumber(at) - dayNumber(today);
  const time = TIME.format(at);
  const hour = at.getHours();

  if (days === 0 && (hour >= 18 || (hour < 6 && today.getHours() < 6))) return `tonight ${time}`;
  if (days === 1 && hour < 6 && today.getHours() >= 12) return `tonight ${time}`;
  if (days === 0) return `today ${time}`;
  if (days === 1) return `tomorrow ${time}`;
  return `${DAY.format(at)} ${time}`;
}

/** A track length or position: "2:41", or "1:02:03" past an hour. Negative counts as 0. */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`;
}

/** Days since the epoch in local time, so a calendar-day difference is a subtraction. */
function dayNumber(date: Date): number {
  return Math.round(new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime() / 86_400_000);
}

// --- For S8's pages ------------------------------------------------------------------------------

const WEEKDAY_DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
const COUNT = new Intl.NumberFormat('en-GB');

/** "Tue 12 Nov" (History's rows with no run). */
export function formatDay(iso: string): string {
  return WEEKDAY_DAY.format(new Date(iso)).replace(',', '');
}

/** "Tue 12 Nov 01:00" (History's When column, a run page's header). */
export function formatDayTime(iso: string): string {
  return `${formatDay(iso)} ${TIME.format(new Date(iso))}`;
}

/**
 * How long ago, seen from `now`: "just now", "5 minutes ago", "3 hours ago", "2 days ago",
 * "1 week ago", then the date (web-ui.md § List view, Last backup: "2 days ago", or "Never").
 * Null gives "Never".
 */
export function formatAgo(iso: string | null, now: number): string {
  if (!iso) return 'Never';
  const minutes = Math.floor((now - Date.parse(iso)) / 60_000);
  const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'} ago`;
  if (minutes < 1) return 'just now';
  if (minutes < 60) return plural(minutes, 'minute');
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return plural(hours, 'hour');
  const days = Math.floor(hours / 24);
  if (days < 7) return plural(days, 'day');
  if (days < 28) return plural(Math.floor(days / 7), 'week');
  return formatDate(iso);
}

/** A run's length: "38 m" under an hour, "5 h 12 m" from an hour (web-ui.md § Runs tab, Duration). */
export function formatRunLength(seconds: number): string {
  const minutes = Math.round(Math.max(0, seconds) / 60);
  if (minutes < 60) return `${minutes} m`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} m`;
}

/**
 * Hours of music, rounded: "about 27 h" uses formatHours(97_305) → "27 h". Under an hour: "45 min".
 * The minutes are rounded first, so 59 min 40 s is "1 h", never "60 min".
 */
export function formatHours(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${Math.max(1, minutes)} min`;
  return `${COUNT.format(Math.round(seconds / 3600))} h`;
}

/** A total length the way a detail header writes it: "7 h 48 min", or "42 min". */
export function formatLength(ms: number): string {
  const minutes = Math.round(Math.max(0, ms) / 60_000);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/**
 * A size in decimal units, as the drawings write them: "9.4 MB", "412 MB", "1.84 TB". One
 * decimal under 10 (two in TB), none from 10.
 */
export function formatBytes(bytes: number): string {
  const units = ['B', 'kB', 'MB', 'GB', 'TB'];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const decimals = value >= 10 || unit === 0 ? 0 : unit === units.length - 1 ? 2 : 1;
  return `${value.toFixed(decimals)} ${units[unit]}`;
}

/** A count with thousands separators: "1,204". */
export function formatCount(n: number): string {
  return COUNT.format(n);
}

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

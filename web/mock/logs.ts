// The mock's logs, for History › Logs (web-ui.md § Logs tab; openapi.yaml listLogs and
// downloadLogs; events.md § Logs). Made-up lines from every source:
// - at each reset, around the sample runs in History, and a few at the mock's "start-up";
// - while a run goes, one or two per event the world publishes (run, item, track, warnings);
// - on demand, through POST /__mock/logs.
// Live: a socket that sent `logs.follow` gets `log.lines` every 0.5 s with the new lines its
// filter matches, 200 at most (the rest counted in `dropped`), and at once the last 10 s.
// Pages: like the controller's, which reads at most about 8 MB per page, a page looks at no more
// than READ_BUDGET lines; then it ends with the lines it found (even none) and a cursor.
// POST /__mock/logs {"read_budget": n} narrows that, to show a sparse search across pages.

import { crc32 } from 'node:zlib';
import type { WebSocket } from 'ws';
import type { HistoryRow, LogLevel, LogLine, LogPage, LogSource } from '../src/api/types.ts';
import type { EventMap, EventType } from '../src/state/events.ts';
import type { ClientMessage, Hub } from './hub.ts';

export const LOG_SOURCES: readonly LogSource[] = ['controller', 'spytify', 'client', 'system'];
export const LOG_LEVELS: readonly LogLevel[] = ['debug', 'info', 'warning', 'error'];
const DEFAULT_LEVELS: readonly LogLevel[] = ['info', 'warning', 'error'];
/** events.md § Logs. */
const BATCH_MAX = 200;
const TAIL_EVERY_MS = 500;
const RECENT_MS = 10_000;
/** A run's lines: 5 s either side of it (openapi.yaml listLogs `run`). */
const RUN_MARGIN_MS = 5_000;
/** Lines a page looks at, at most (the controller's 8 MB, scaled to the mock's few hundred lines). */
const READ_BUDGET = 1000;
const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;

interface Entry {
  line: LogLine;
  ns: bigint;
}

export interface LogFilter {
  sources: readonly LogSource[] | null;
  levels: readonly LogLevel[];
  run: number | null;
  /** The run's time, with the margin: [start, end], end null while it goes on. */
  span: [number, number | null] | null;
  q: string | null;
}

interface Follower {
  filter: LogFilter;
  followId: number | string | null;
}

/** A line as the controller's `id`: `<at_ns>-<dup>-<service>`. */
function idOf(ns: bigint, dup: number, service: string): string {
  return `${ns}-${dup}-${service}`;
}

/** The key in an `id` or `before`, or null when it isn't one. */
export function decodeKey(text: string): { ns: bigint; service: string; dup: number } | null {
  const match = /^(\d{1,20})-(\d{1,9})-([A-Za-z0-9_.-]{0,100})$/.exec(text);
  if (!match) return null;
  return { ns: BigInt(match[1] ?? '0'), dup: Number(match[2]), service: match[3] ?? '' };
}

function compareKeys(a: { ns: bigint; service: string; dup: number }, b: { ns: bigint; service: string; dup: number }): number {
  if (a.ns !== b.ns) return a.ns < b.ns ? -1 : 1;
  if (a.service !== b.service) return a.service < b.service ? -1 : 1;
  return a.dup - b.dup;
}

function keyOf(entry: Entry) {
  const dup = Number(entry.line.id.split('-')[1] ?? 0);
  return { ns: entry.ns, service: entry.line.service, dup };
}

/** The made-up lines for one sample run: its start and end, a few items, and trouble to match its outcome. */
function runLines(row: HistoryRow, add: Adder) {
  if (row.kind !== 'run' || !row.ended_at) return;
  const start = Date.parse(row.started_at);
  const end = Date.parse(row.ended_at);
  const length = Math.max(end - start, 2 * MINUTE);
  const trigger = row.trigger === 'run_now' ? 'Run now' : row.trigger === 'startup' ? 'Start-up' : 'Scheduled';
  add(start, 'controller', 'controller', 'info', `runs: run ${row.id} started (${trigger}), 3 items`);
  add(start + 400, 'controller', 'controller', 'info', 'catalog: refresh done: 2 requests, nothing changed');
  add(start + 900, 'controller', 'controller', 'debug', 'item Liked Songs: planning, 41 missing');
  const items = [
    { service: `${row.id}-liked`, name: 'Liked Songs' },
    { service: `${row.id}-3cEYpjA9oz9GiPac4AsH4n`, name: 'Late Night Drive' },
  ];
  const tracks = ['Ribs', 'Ocean Eyes', 'Holocene', 'Go Your Own Way', 'Mr. Brightside', 'Born to Run', 'Highway Tune', 'Dreams'];
  items.forEach((item, n) => {
    const from = start + 2 * SECOND + (n * length) / 2;
    add(from - 600, 'controller', 'controller', 'info', `item ${item.name}: started`);
    add(from, 'spytify', item.service, 'info', `session ${new Date(from).toISOString().slice(0, 19).replace(/\D/g, '')} started`, row.id);
    add(from + 30, 'spytify', item.service, 'debug', 'player: volume raised from 0% to 100% for the session', row.id);
    // Enough lines that the newest runs fill more than a page.
    const count = row.id === 41 ? 60 : 12;
    for (let t = 0; t < count; t += 1) {
      const at = from + SECOND + (t * (length / 2 - 4 * SECOND)) / count;
      const title = tracks[t % tracks.length] ?? 'Track';
      add(at, 'spytify', item.service, 'info', `track.started "${title}" ${3 + (t % 3)}:${String(10 + ((t * 7) % 50)).padStart(2, '0')}`, row.id);
      if (t % 4 === 1) add(at + 900, 'spytify', item.service, 'info', `track.skipped "${title}" duplicate`, row.id);
      else add(at + 1500, 'spytify', item.service, 'info', `track.finished "${title}" ${(6 + (t % 5) * 0.7).toFixed(1)} MB`, row.id);
    }
    add(from + length / 2 - 2 * SECOND, 'controller', 'controller', 'info', `item ${item.name}: done`);
  });
  if (row.outcome === 'completed_with_issues') {
    const at = start + length / 3;
    add(at, 'spytify', items[0]?.service ?? '', 'warning', 'level peaks below threshold, marking take as low volume', row.id);
    add(at + 1000, 'spytify', items[0]?.service ?? '', 'error', 'track.failed "Holocene" low volume', row.id);
    add(at + 3000, 'client', 'spotify', 'warning', 'Warning: PlaybackPaused: network stall 24s');
    add(at + 3500, 'controller', 'controller', 'warning', 'item Late Night Drive: interrupted, re-queued at the end');
  }
  if (row.outcome === 'failed') {
    add(end, 'controller', 'controller', 'error', `runs: run ${row.id} failed: the container restarted`);
  }
  if (row.outcome === 'window_ended') {
    add(end - SECOND, 'controller', 'controller', 'info', 'schedule: the window ended: stopping after this track');
  }
  add(end, 'controller', 'controller', 'info', `runs: run ${row.id} ended: ${row.outcome ?? 'done'}`);
  add(end + 200, 'controller', 'controller', 'info', 'Web API: 112 requests · 2 retried · 0 rate-limited');
}

type Adder = (atMs: number, source: LogSource, service: string, level: LogLevel, message: string, runId?: number | null) => void;

export function createLogBook(hub: Hub, history: () => HistoryRow[], liveRun: () => HistoryRow | null) {
  let entries: Entry[] = [];
  /** Lines added since the last tail tick, for the followers. */
  let fresh: Entry[] = [];
  const followers = new Map<WebSocket, Follower>();
  /** Lines so far per time and service, for `dup`: "<ns>|<service>" → count. */
  const dups = new Map<string, number>();
  let tailTimer: ReturnType<typeof setInterval> | null = null;
  let readBudget = READ_BUDGET;

  const add = (atMs: number, source: LogSource, service: string, level: LogLevel, message: string, runId: number | null = null): Entry => {
    const ns = BigInt(Math.round(atMs)) * 1_000_000n;
    const slot = `${ns}|${service}`;
    const dup = dups.get(slot) ?? 0;
    dups.set(slot, dup + 1);
    const entry: Entry = {
      ns,
      line: {
        id: idOf(ns, dup, service),
        at: new Date(Math.round(atMs)).toISOString(),
        source,
        service,
        level,
        message,
        run_id: source === 'spytify' ? runId : null,
      },
    };
    entries.push(entry);
    return entry;
  };

  /** Adds a line now, and hands it to the live tail. */
  function addNow(source: LogSource, service: string, level: LogLevel, message: string, runId: number | null = null) {
    fresh.push(add(Date.now(), source, service, level, message, runId));
    startTail();
  }

  function sort() {
    entries.sort((a, b) => compareKeys(keyOf(a), keyOf(b)));
  }

  /** The sample logs: a start-up a few hours ago, the sample runs, and some chatter since. */
  function seed() {
    entries = [];
    fresh = [];
    dups.clear();
    readBudget = READ_BUDGET;
    const now = Date.now();
    const boot = now - 3 * HOUR;
    for (const row of history()) runLines(row, add);
    add(boot, 'system', 'init', 'info', 'DEVICE_NAME=spotivault TZ=Europe/Berlin UMASK=000');
    add(boot + 300, 'system', 'xserver', 'warning', '(WW) Option "-nolisten" is deprecated');
    add(boot + 500, 'system', 'pulseaudio', 'warning', 'W: [pulseaudio] module-null-sink: latency is high');
    add(boot + 800, 'system', 'vnc', 'info', 'The VNC desktop is:      localhost:0');
    add(boot + 1200, 'client', 'spotify', 'warning', 'Warning: no GPU found, drawing in software');
    add(boot + 1300, 'client', 'spotify', 'error', '[1121/183738.292224:ERROR:gpu_init.cc(441)] Passthrough is not supported, GL is swiftshader');
    add(boot + 2000, 'controller', 'controller', 'info', 'Started server process [152]');
    add(boot + 2100, 'controller', 'controller', 'info', 'client: installed, running, logged in');
    for (let n = 0; n < 12; n += 1) {
      add(now - (12 - n) * 10 * MINUTE, 'controller', 'controller', 'info', `catalog: refresh (page open): nothing new, ${2 + (n % 2)} requests`);
      add(now - (12 - n) * 10 * MINUTE + 50, 'controller', 'controller', 'debug', 'events: a client connected (1 open)');
    }
    sort();
  }

  function filterOf(query: {
    source?: readonly string[] | null;
    level?: readonly string[] | null;
    run?: number | null;
    q?: string | null;
  }): LogFilter | 'unknown_run' {
    const run = query.run ?? null;
    let span: [number, number | null] | null = null;
    if (run !== null) {
      const live = liveRun();
      const row = live && live.id === run ? live : history().find((r) => r.id === run && r.kind === 'run');
      if (!row) return 'unknown_run';
      span = [Date.parse(row.started_at) - RUN_MARGIN_MS, row.ended_at ? Date.parse(row.ended_at) + RUN_MARGIN_MS : null];
    }
    return {
      sources: query.source && query.source.length ? (query.source as LogSource[]) : null,
      levels: query.level && query.level.length ? (query.level as LogLevel[]) : DEFAULT_LEVELS,
      run,
      span,
      q: query.q ? query.q.toLowerCase() : null,
    };
  }

  function matches(filter: LogFilter, line: LogLine): boolean {
    if (filter.sources && !filter.sources.includes(line.source)) return false;
    if (!filter.levels.includes(line.level)) return false;
    if (filter.run !== null) {
      if (line.source === 'spytify') {
        if (line.run_id !== filter.run) return false;
      } else if (filter.span) {
        const at = Date.parse(line.at);
        if (at < filter.span[0] || (filter.span[1] !== null && at > filter.span[1])) return false;
      }
    }
    if (filter.q && !line.message.toLowerCase().includes(filter.q)) return false;
    return true;
  }

  // --- Live -------------------------------------------------------------------------------------

  function startTail() {
    if (tailTimer || followers.size === 0) return;
    tailTimer = setInterval(tick, TAIL_EVERY_MS);
    tailTimer.unref();
  }

  function tick() {
    const lines = fresh;
    fresh = [];
    if (lines.length > 0) sort();
    closeEndedRuns();
    for (const [socket, follower] of followers) send(socket, follower, lines);
    if (followers.size === 0 && tailTimer) {
      clearInterval(tailTimer);
      tailTimer = null;
    }
  }

  /** A follower of a run that was going: once it ended, its lines stop 5 s later. */
  function closeEndedRuns() {
    const live = liveRun();
    for (const follower of followers.values()) {
      const { filter } = follower;
      if (filter.run !== null && filter.span && filter.span[1] === null && live?.id !== filter.run) {
        filter.span = [filter.span[0], Date.now() + RUN_MARGIN_MS];
      }
    }
  }

  function send(socket: WebSocket, follower: Follower, lines: Entry[]) {
    const matched = lines.map((e) => e.line).filter((line) => matches(follower.filter, line));
    if (matched.length === 0) return;
    const dropped = Math.max(0, matched.length - BATCH_MAX);
    hub.sendVolatile(socket, 'log.lines', { lines: matched.slice(-BATCH_MAX), dropped, follow_id: follower.followId });
  }

  hub.onMessage((socket, message: ClientMessage | null) => {
    if (message === null || message.type === 'logs.unfollow') {
      followers.delete(socket);
      return;
    }
    if (message.type !== 'logs.follow') return;
    const raw = (message.filter ?? {}) as Record<string, unknown>;
    const asList = (value: unknown, allowed: readonly string[]) =>
      Array.isArray(value) && value.every((v) => typeof v === 'string' && allowed.includes(v)) ? (value as string[]) : null;
    const filter = filterOf({
      source: asList(raw.source, LOG_SOURCES),
      level: asList(raw.level, LOG_LEVELS),
      run: typeof raw.run === 'number' ? raw.run : null,
      q: typeof raw.q === 'string' ? raw.q : null,
    });
    const followId = typeof message.follow_id === 'number' || typeof message.follow_id === 'string' ? message.follow_id : null;
    // A run the mock doesn't know: nothing matches.
    const follower: Follower = {
      filter: filter === 'unknown_run' ? { sources: null, levels: [], run: null, span: null, q: null } : filter,
      followId,
    };
    followers.set(socket, follower);
    // The last 10 s at once: a page read and the follow can cross (events.md § Logs).
    const since = Date.now() - RECENT_MS;
    send(socket, follower, entries.filter((e) => Date.parse(e.line.at) >= since));
    startTail();
  });

  // The world's events, as the controller would log them.
  hub.onPublish(<K extends EventType>(type: K, data: EventMap[K]) => {
    const event = { type, data } as { [T in EventType]: { type: T; data: EventMap[T] } }[EventType];
    switch (event.type) {
      case 'run.state': {
        const run = event.data;
        if (run.state === run.previous_state) return;
        if (run.state === 'paused') addNow('controller', 'controller', 'warning', `runs: run ${run.id} paused: ${run.paused_reason === 'device_moved' ? 'playback moved' : 'another device is playing'}`);
        else if (run.state !== 'idle') addNow('controller', 'controller', 'info', `runs: run ${run.id} ${run.state}`);
        return;
      }
      case 'item.state': {
        const { item, previous_state: previous } = event.data;
        if (item.state === previous) return;
        const level: LogLevel = item.state === 'partial' || item.state === 'failed' || item.state === 'interrupted' ? 'warning' : 'info';
        addNow('controller', 'controller', level, `item ${item.name}: ${previous} → ${item.state}${item.reason ? ` (${item.reason})` : ''}`);
        if (item.state === 'planning') addNow('controller', 'controller', 'debug', `item ${item.name}: planning the takes`);
        return;
      }
      case 'track.started': {
        const t = event.data;
        addNow('spytify', `${t.run_id}-${t.item_id}`, 'info', `track.started "${t.title}" ${t.artist}`, t.run_id);
        return;
      }
      case 'track.finished': {
        const t = event.data;
        const what = t.counted ? `${(t.bytes / 1_000_000).toFixed(1)} MB` : t.low_volume ? 'low volume, not kept' : 'not kept';
        addNow('spytify', `${t.run_id}-${t.item_id}`, t.counted ? 'info' : 'warning', `track.finished ${t.path ?? ''} ${what}`.replace(/\s+/g, ' '), t.run_id);
        return;
      }
      case 'track.skipped': {
        const t = event.data;
        addNow('spytify', `${t.run_id}-${t.item_id}`, 'info', `track.skipped ${t.reason}`, t.run_id);
        return;
      }
      case 'error': {
        const e = event.data;
        const level: LogLevel = e.withdrawn ? 'info' : e.fatal ? 'error' : 'warning';
        const text = e.withdrawn ? `${e.code}: withdrawn` : `${e.code}: ${e.message}`;
        if (e.source === 'spytify' && e.run_id !== null && e.item_id !== null) addNow('spytify', `${e.run_id}-${e.item_id}`, level, text, e.run_id);
        else addNow('controller', 'controller', level, text);
        return;
      }
      case 'device.moved':
        addNow('controller', 'controller', 'warning', `runs: playback moved to ${event.data.device.name}`);
        return;
      case 'run.finished': {
        const row = event.data.run;
        if (row.kind === 'run') addNow('controller', 'controller', 'info', `runs: run ${row.id} finished: ${row.outcome ?? 'done'}`);
        return;
      }
      default:
        return;
    }
  });

  seed();

  return {
    /** Starts over: the sample lines for the world's History now. */
    reset: seed,
    /** GET /api/logs: a page, newest first back from `before`, oldest first in the answer. */
    page(query: {
      source: string[];
      level: string[];
      run: number | null;
      q: string | null;
      before: string | null;
      limit: number;
    }): LogPage | 'unknown_run' | 'bad_before' {
      const filter = filterOf(query);
      if (filter === 'unknown_run') return 'unknown_run';
      const before = query.before === null ? null : decodeKey(query.before);
      if (query.before !== null && before === null) return 'bad_before';
      const out: LogLine[] = [];
      let last: LogLine | null = null;
      let more = false;
      /** Lines looked at, and the last one: past the budget, the next page starts below it. */
      let looked = 0;
      let lastLooked: LogLine | null = null;
      for (let i = entries.length - 1; i >= 0; i -= 1) {
        const entry = entries[i];
        if (!entry) continue;
        if (before && compareKeys(keyOf(entry), before) >= 0) continue;
        if (filter.span && Date.parse(entry.line.at) < filter.span[0]) break; // older than the run
        if (looked >= readBudget && lastLooked) return { lines: out.reverse(), next_before: lastLooked.id };
        looked += 1;
        lastLooked = entry.line;
        if (!matches(filter, entry.line)) continue;
        if (out.length >= query.limit) {
          more = true;
          break;
        }
        out.push(entry.line);
        last = entry.line;
      }
      return { lines: out.reverse(), next_before: more && last ? last.id : null };
    },
    /** POST /__mock/logs: lines now, for the live tail. */
    addLines(lines: { source: LogSource; level: LogLevel; message: string; service?: string; run_id?: number | null }[]) {
      for (const l of lines) {
        const service = l.service ?? (l.source === 'controller' ? 'controller' : l.source === 'client' ? 'spotify' : l.source === 'system' ? 'dbus' : '1-liked');
        addNow(l.source, service, l.level, l.message, l.run_id ?? null);
      }
    },
    /** POST /__mock/logs {"burst": n}: n controller lines at once, more than one batch holds. */
    burst(count: number) {
      for (let n = 1; n <= count; n += 1) addNow('controller', 'controller', 'info', `burst line ${n} of ${count}`);
    },
    /** POST /__mock/logs {"read_budget": n}: a page looks at n lines at most, until the next reset. */
    setReadBudget(lines: number) {
      readBudget = lines;
    },
    /** POST /__mock/logs {"empty": true}: no lines at all. */
    empty() {
      entries = [];
      fresh = [];
      dups.clear();
    },
    followers: () => followers.size,
    close() {
      if (tailTimer) clearInterval(tailTimer);
      tailTimer = null;
      followers.clear();
    },
  };
}

export type LogBook = ReturnType<typeof createLogBook>;

/**
 * GET /api/logs/download: a tiny made-up zip (stored, no compression) with two files in the
 * container's formats. Enough for the UI's download; the controller's has every log.
 */
export function sampleZip(now: Date = new Date()): Buffer {
  const s6 = (ms: number, text: string) => `${new Date(ms).toISOString().replace('T', ' ').replace('Z', '')}000000  ${text}\n`;
  const t = now.getTime();
  const files: [string, string][] = [
    ['controller/current', s6(t - 60_000, 'INFO spotivault.engine.run: runs: run 41 started (Scheduled)') + s6(t - 30_000, 'WARNING spotivault.loopwatch: loop: 300 ms late')],
    ['spytify/41-liked.log', `${new Date(t - 50_000).toISOString().replace('Z', '000000Z')} info  session started\n`],
  ];
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const [name, text] of files) {
    const nameBytes = Buffer.from(name, 'utf8');
    const data = Buffer.from(text, 'utf8');
    const crc = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4); // version needed
    local.writeUInt16LE(0x0800, 6); // UTF-8 names
    local.writeUInt16LE(0, 8); // stored
    local.writeUInt32LE(0, 10); // time and date: 1980
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    local.writeUInt16LE(0, 28);
    locals.push(local, nameBytes, data);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt32LE(0, 12);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, nameBytes);
    offset += 30 + nameBytes.length + data.length;
  }
  const centralSize = centrals.reduce((n, b) => n + b.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, ...centrals, end]);
}

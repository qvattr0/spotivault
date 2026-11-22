// @vitest-environment node
// The mock's History › Logs (mock/logs.ts) against the contract and events.md § Logs: pages and
// their filters, the live tail after logs.follow (its first batch, the 200-line cap, a run going
// on as lines), the zip, and POST /__mock/logs.

import { afterEach, describe, expect, it } from 'vitest';
import { WebSocket } from 'ws';
import type { LogLine, LogPage } from '../src/api/types.ts';
import { createHub, type Hub } from './hub.ts';
import { handle } from './routes.ts';
import { sampleZip } from './logs.ts';
import { startMockServer, type MockServer } from './server.ts';
import { createWorld, type World } from './world.ts';

let open: { world: World; hub: Hub }[] = [];
let servers: MockServer[] = [];

function world(scenario: 'idle' | 'running' = 'idle'): World {
  const hub = createHub({ background: true });
  const w = createWorld(hub, scenario, { speed: 50 });
  open.push({ world: w, hub });
  return w;
}

afterEach(async () => {
  for (const { world: w, hub } of open) {
    w.close();
    hub.close();
  }
  open = [];
  await Promise.all(servers.map((s) => s.close()));
  servers = [];
});

function get(w: World, path: string) {
  return handle(w, 'GET', new URL(`http://mock${path}`), {});
}

function page(w: World, query = ''): LogPage {
  const reply = get(w, `/api/logs${query}`);
  expect(reply.status).toBe(200);
  return reply.body as LogPage;
}

describe('GET /api/logs', () => {
  it('pages back through every source, oldest first in a page, each line once', () => {
    const w = world();
    const seen: LogLine[] = [];
    let before: string | null = null;
    let pages = 0;
    do {
      const p: LogPage = page(w, `?limit=100${before ? `&before=${before}` : ''}`);
      expect(p.lines.map((l) => l.at)).toEqual(p.lines.map((l) => l.at).sort());
      seen.unshift(...p.lines);
      before = p.next_before;
      pages += 1;
    } while (before);
    expect(pages).toBeGreaterThan(2);
    expect(new Set(seen.map((l) => l.id)).size).toBe(seen.length);
    expect(new Set(seen.map((l) => l.source))).toEqual(new Set(['controller', 'spytify', 'client', 'system']));
    expect(seen.some((l) => l.level === 'debug')).toBe(false); // not unless asked
  });

  it('filters by source, level, run and search, as the contract says', () => {
    const w = world();
    const errors = page(w, '?level=error&source=client&source=controller').lines;
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.every((l) => l.level === 'error' && (l.source === 'client' || l.source === 'controller'))).toBe(true);
    expect(page(w, '?level=debug').lines.every((l) => l.level === 'debug')).toBe(true);

    const run = page(w, '?run=41&limit=500').lines;
    expect(run.some((l) => l.message === 'runs: run 41 started (Scheduled), 3 items')).toBe(true);
    expect(run.filter((l) => l.source === 'spytify').every((l) => l.run_id === 41)).toBe(true);
    expect(run.some((l) => l.message.startsWith('runs: run 40'))).toBe(false);

    const search = page(w, '?q=HOLOCENE').lines;
    expect(search.length).toBeGreaterThan(0);
    expect(search.every((l) => l.message.toLowerCase().includes('holocene'))).toBe(true);

    expect(get(w, '/api/logs?run=9999').status).toBe(404);
    expect(get(w, '/api/logs?before=x%20y').status).toBe(422);
    expect(get(w, '/api/logs?level=loud').status).toBe(422);
    expect(get(w, '/api/logs?limit=501').status).toBe(422);
  });

  it('stops a page at its read budget, with the lines it found (even none) and a cursor', () => {
    const w = world();
    const all = page(w, '?q=DEVICE_NAME').lines;
    expect(all).toHaveLength(1);
    expect(handle(w, 'POST', new URL('http://mock/__mock/logs'), { read_budget: 5 }).status).toBe(204);
    expect(handle(w, 'POST', new URL('http://mock/__mock/logs'), { read_budget: 0 }).status).toBe(422);
    const first = page(w, '?q=DEVICE_NAME');
    expect(first.lines).toEqual([]);
    expect(first.next_before).not.toBeNull();
    // Paging on finds it, each page looking at 5 lines; a page of every line holds 5 at most.
    let before = first.next_before;
    let found: LogLine[] = [];
    for (let n = 0; n < 50 && before && found.length === 0; n += 1) {
      const next: LogPage = page(w, `?q=DEVICE_NAME&before=${before}`);
      found = next.lines;
      before = next.next_before;
    }
    expect(found.map((l) => l.id)).toEqual(all.map((l) => l.id));
    expect(page(w).lines.length).toBeLessThanOrEqual(5);
    // A scenario starts over with the usual budget.
    w.reset('idle');
    expect(page(w, '?q=DEVICE_NAME').lines).toHaveLength(1);
  });

  it('empties, and adds lines on demand (POST /__mock/logs)', () => {
    const w = world();
    expect(handle(w, 'POST', new URL('http://mock/__mock/logs'), { empty: true }).status).toBe(204);
    expect(page(w).lines).toEqual([]);
    handle(w, 'POST', new URL('http://mock/__mock/logs'), { add: [{ source: 'system', level: 'warning', message: 'W: [pulseaudio] slow' }] });
    expect(page(w).lines).toMatchObject([{ source: 'system', level: 'warning', message: 'W: [pulseaudio] slow' }]);
    expect(handle(w, 'POST', new URL('http://mock/__mock/logs'), { add: [{ source: 'nope' }] }).status).toBe(422);
  });
});

describe('GET /api/logs/download', () => {
  it('answers a small zip of made-up logs', () => {
    const w = world();
    const reply = get(w, '/api/logs/download?days=7');
    expect(reply.status).toBe(200);
    expect(reply.contentType).toBe('application/zip');
    expect(reply.headers?.['Content-Disposition']).toMatch(/^attachment; filename="spotivault-logs-\d{8}-\d{4}\.zip"$/);
    expect(get(w, '/api/logs/download?days=15').status).toBe(422);

    const zip = sampleZip();
    expect(zip.readUInt32LE(0)).toBe(0x04034b50);
    const nameLength = zip.readUInt16LE(26);
    expect(zip.subarray(30, 30 + nameLength).toString()).toBe('controller/current');
    const size = zip.readUInt32LE(18);
    const text = zip.subarray(30 + nameLength, 30 + nameLength + size).toString();
    expect(text).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{9} {2}INFO /);
  });
});

describe('the live tail', () => {
  async function follow(mock: MockServer, filter: Record<string, unknown> = {}) {
    const socket = new WebSocket(`ws://localhost:${mock.port}/api/events`);
    const batches: { lines: LogLine[]; dropped: number; follow_id: number | null; seq: unknown }[] = [];
    socket.on('message', (raw) => {
      const event = JSON.parse(String(raw)) as { type: string; seq: unknown; data: { lines: LogLine[]; dropped: number; follow_id: number | null } };
      if (event.type === 'hello') socket.send(JSON.stringify({ type: 'logs.follow', follow_id: 5, filter }));
      if (event.type === 'log.lines') batches.push({ ...event.data, seq: event.seq });
    });
    await new Promise((resolve) => socket.on('open', resolve));
    return { socket, batches };
  }

  async function mockIn(scenario: 'idle' | 'running') {
    const mock = await startMockServer({ port: 0, scenario, quiet: true, background: true, speed: 10 });
    servers.push(mock);
    return mock;
  }

  it('sends nothing until asked, then the matching new lines in batches, 200 at most', async () => {
    const mock = await mockIn('idle');
    const quiet = new WebSocket(`ws://localhost:${mock.port}/api/events`);
    const quietTypes: string[] = [];
    quiet.on('message', (raw) => quietTypes.push((JSON.parse(String(raw)) as { type: string }).type));
    const { socket, batches } = await follow(mock, { level: ['warning', 'error'] });
    await expect.poll(() => quietTypes.length).toBeGreaterThan(0);

    const post = (body: unknown) =>
      fetch(`http://localhost:${mock.port}/__mock/logs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    await new Promise((resolve) => setTimeout(resolve, 100)); // the follow arrives
    await post({ add: [{ source: 'controller', level: 'info', message: 'not wanted' }, { source: 'spytify', level: 'error', message: 'capture failed' }] });
    await expect.poll(() => batches.flatMap((b) => b.lines).map((l) => l.message)).toContain('capture failed');
    expect(batches.flatMap((b) => b.lines).map((l) => l.message)).not.toContain('not wanted');
    expect(batches[0]).toMatchObject({ seq: null, follow_id: 5, dropped: 0 });

    socket.send(JSON.stringify({ type: 'logs.follow', follow_id: 6, filter: {} }));
    await new Promise((resolve) => setTimeout(resolve, 100));
    await post({ burst: 450 });
    await expect.poll(() => batches.some((b) => b.follow_id === 6 && b.dropped > 0), { timeout: 3000 }).toBe(true);
    const capped = batches.find((b) => b.follow_id === 6 && b.dropped > 0);
    expect(capped?.lines).toHaveLength(200);
    expect(capped?.lines.at(-1)?.message).toBe('burst line 450 of 450');
    expect(quietTypes).not.toContain('log.lines');
    socket.close();
    quiet.close();
  });

  it('turns a run going on into lines, and a follow of that run gets them', async () => {
    const mock = await mockIn('running');
    const status = (await (await fetch(`http://localhost:${mock.port}/api/status`)).json()) as { run: { id: number } };
    const { socket, batches } = await follow(mock, { run: status.run.id });
    await expect
      .poll(() => batches.flatMap((b) => b.lines).some((l) => l.source === 'spytify' && l.message.startsWith('track.')), { timeout: 8000 })
      .toBe(true);
    expect(batches.flatMap((b) => b.lines).filter((l) => l.source === 'spytify').every((l) => l.run_id === status.run.id)).toBe(true);
    socket.close();
  });
});

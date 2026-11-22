// The mock backend: a stand-in for the controller during UI work. REST under /api, the live
// events on WS /api/events, and /__mock/* controls. It follows contracts/openapi.yaml and
// contracts/events.md.
//
//   npm run mock                          on port 8081, scenario "idle"
//   MOCK_PORT=9000 MOCK_SCENARIO=running npm run mock
//   MOCK_SPEED=10 npm run dev             runs and installs 10 times faster
//
// `npm run dev` starts it by itself (vite.config.ts). Scenarios are listed in fixtures.ts.

import { createServer, type IncomingMessage } from 'node:http';
import type { AddressInfo } from 'node:net';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { SCENARIOS, type Scenario } from './fixtures.ts';
import { createHub } from './hub.ts';
import { handle } from './routes.ts';
import { serveVnc } from './vnc.ts';
import { createWorld } from './world.ts';

export interface MockServer {
  port: number;
  close(): Promise<void>;
}

export interface MockOptions {
  port?: number;
  /** One of SCENARIOS. Defaults to "idle". */
  scenario?: string;
  /** Don't print a line on start. */
  quiet?: boolean;
  /** Started inside another process (Vite): don't keep that process alive on its own. */
  background?: boolean;
  /** Runs the simulations this many times faster. Defaults to MOCK_SPEED, or 1. */
  speed?: number;
}

async function readJson(req: IncomingMessage): Promise<Record<string, unknown> | 'invalid'> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  const text = Buffer.concat(chunks).toString('utf8');
  if (!text) return {};
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : 'invalid';
  } catch {
    return 'invalid';
  }
}

export function startMockServer(options: MockOptions = {}): Promise<MockServer> {
  const scenario: Scenario = SCENARIOS.includes(options.scenario as Scenario) ? (options.scenario as Scenario) : 'idle';
  const hub = createHub({ background: options.background });
  const world = createWorld(hub, scenario, { speed: options.speed ?? Number(process.env.MOCK_SPEED ?? 1) });

  const server = createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://mock');
    const body = await readJson(req);
    const reply =
      body === 'invalid'
        ? { status: 422, body: { error: { code: 'validation_failed', message: 'The body is not JSON.', details: null } } }
        : handle(world, req.method ?? 'GET', url, body);

    if (reply.contentType) {
      res.writeHead(reply.status, { 'Content-Type': reply.contentType, 'Cache-Control': 'private, max-age=86400', ...reply.headers });
      res.end(reply.body as string | Buffer);
    } else if (reply.body === undefined) {
      res.writeHead(reply.status);
      res.end();
    } else {
      res.writeHead(reply.status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(reply.body));
    }
  });

  const wss = new WebSocketServer({ noServer: true });
  server.on('upgrade', (req, socket, head) => {
    const path = new URL(req.url ?? '/', 'http://mock').pathname;
    wss.handleUpgrade(req, socket, head, (ws) => {
      if (path === '/api/events') {
        hub.add(ws, world.hello());
      } else if (path === '/vnc') {
        // A small fake screen (mock/vnc.ts); 1013 while the screen "isn't up yet", as the controller.
        if (world.data.vncUp) serveVnc(ws, world);
        else ws.close(1013, 'The screen is not up yet.');
      } else {
        ws.close(4000, 'Unknown WebSocket path.');
      }
    });
  });

  const port = options.port ?? 8081;
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    if (options.background) server.unref();
    server.listen(port, () => {
      // With port 0 the system picks a free one.
      const actual = (server.address() as AddressInfo).port;
      if (!options.quiet) console.log(`mock backend: http://localhost:${actual} (scenario "${scenario}")`);
      resolve({
        port: actual,
        close: () =>
          new Promise<void>((done) => {
            world.close();
            hub.close();
            wss.close();
            server.closeAllConnections();
            server.close(() => done());
          }),
      });
    });
  });
}

// Run directly: `node mock/server.ts`.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const mock = await startMockServer({
    port: Number(process.env.MOCK_PORT ?? 8081),
    scenario: process.env.MOCK_SCENARIO,
  });
  const stop = () => void mock.close().then(() => process.exit(0));
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}

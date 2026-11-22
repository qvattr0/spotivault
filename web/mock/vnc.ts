// A tiny VNC server on WS /vnc, so the noVNC view (wizard steps 3 and 4, the Player) shows a screen
// against the mock, as it does against the controller's fake mode (controller/src/spotivault/fake/
// vnc.py, which this follows). RFB 3.8, no authentication, raw encoding: what noVNC needs.
//
// The screen follows the mock's client:
// - not installed or not running: black, as Xvfb with no window;
// - logged out: a login screen with a QR-like code. A click on it logs the client in, standing in
//   for scanning the code with a phone (as in fake mode);
// - logged in: a dark player window with a bottom bar.
//
// While the world says the screen isn't up (POST /__mock/vnc {"up": false}), server.ts closes the
// socket with 1013, as the controller does before Xvfb is up.

import type { RawData, WebSocket } from 'ws';
import type { World } from './world.ts';

const WIDTH = 1280;
const HEIGHT = 800;
const NAME = Buffer.from('spotivault mock screen');

type Rgb = [number, number, number];
type Scene = 'off' | 'login' | 'player';

interface PixelFormat {
  bits: number;
  bigEndian: boolean;
  redMax: number;
  greenMax: number;
  blueMax: number;
  redShift: number;
  greenShift: number;
  blueShift: number;
}

const DEFAULT_FORMAT: PixelFormat = {
  bits: 32, bigEndian: false, redMax: 255, greenMax: 255, blueMax: 255, redShift: 16, greenShift: 8, blueShift: 0,
};

function packFormat(fmt: PixelFormat): Buffer {
  const b = Buffer.alloc(16);
  b.writeUInt8(fmt.bits, 0);
  b.writeUInt8(24, 1); // depth
  b.writeUInt8(fmt.bigEndian ? 1 : 0, 2);
  b.writeUInt8(1, 3); // true colour
  b.writeUInt16BE(fmt.redMax, 4);
  b.writeUInt16BE(fmt.greenMax, 6);
  b.writeUInt16BE(fmt.blueMax, 8);
  b.writeUInt8(fmt.redShift, 10);
  b.writeUInt8(fmt.greenShift, 11);
  b.writeUInt8(fmt.blueShift, 12);
  return b;
}

function readFormat(b: Buffer): PixelFormat {
  return {
    bits: b.readUInt8(0), bigEndian: b.readUInt8(2) !== 0,
    redMax: b.readUInt16BE(4), greenMax: b.readUInt16BE(6), blueMax: b.readUInt16BE(8),
    redShift: b.readUInt8(10), greenShift: b.readUInt8(11), blueShift: b.readUInt8(12),
  };
}

function pixel(fmt: PixelFormat, [r, g, b]: Rgb): Buffer {
  const value =
    (((r * fmt.redMax) / 255) << fmt.redShift) |
    (((g * fmt.greenMax) / 255) << fmt.greenShift) |
    (((b * fmt.blueMax) / 255) << fmt.blueShift);
  const out = Buffer.alloc(4);
  if (fmt.bigEndian) out.writeUInt32BE(value >>> 0);
  else out.writeUInt32LE(value >>> 0);
  return out;
}

function sceneOf(world: World): Scene {
  const client = world.data.client;
  if (!client.installed || !client.running) return 'off';
  return client.logged_in ? 'player' : 'login';
}

/** A QR finder square in three corners: true dark, false light, null outside them. */
function inFinder(row: number, col: number, modules: number): boolean | null {
  for (const [top, left] of [[0, 0], [0, modules - 7], [modules - 7, 0]] as const) {
    const r = row - top;
    const c = col - left;
    if (r >= 0 && r < 7 && c >= 0 && c < 7) return r === 0 || r === 6 || c === 0 || c === 6 || (r >= 2 && r <= 4 && c >= 2 && c <= 4);
  }
  return null;
}

/** Draws a scene: a few filled rectangles, like fake mode's screen. */
function render(scene: Scene, fmt: PixelFormat): Buffer {
  const frame = Buffer.alloc(WIDTH * HEIGHT * 4);
  const fill = (x: number, y: number, w: number, h: number, rgb: Rgb) => {
    const row = Buffer.alloc(w * 4).fill(pixel(fmt, rgb));
    for (let line = y; line < y + h; line++) row.copy(frame, (line * WIDTH + x) * 4);
  };
  fill(0, 0, WIDTH, HEIGHT, scene === 'off' ? [0, 0, 0] : [18, 18, 18]);
  if (scene === 'login') {
    // A QR-like code: 25 × 25 modules of 12 px on white, with finder squares in three corners.
    const modules = 25;
    const size = 12;
    const left = (WIDTH - modules * size) / 2;
    const top = 180;
    fill(left - 24, top - 24, modules * size + 48, modules * size + 48, [255, 255, 255]);
    let seed = 7;
    for (let row = 0; row < modules; row++) {
      for (let col = 0; col < modules; col++) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        const finder = inFinder(row, col, modules);
        if (finder ?? (seed >> 16) % 2 === 0) fill(left + col * size, top + row * size, size, size, [0, 0, 0]);
      }
    }
    fill((WIDTH - 280) / 2, top + modules * size + 70, 280, 48, [30, 215, 96]);
  } else if (scene === 'player') {
    fill(0, 0, 240, HEIGHT - 72, [0, 0, 0]);
    fill(0, HEIGHT - 72, WIDTH, 72, [24, 24, 24]);
    fill(16, HEIGHT - 60, 48, 48, [83, 83, 83]);
    fill(340, HEIGHT - 22, 600, 4, [83, 83, 83]);
    fill(WIDTH / 2 - 16, HEIGHT - 64, 32, 32, [255, 255, 255]);
  }
  return frame;
}

/** Serves one noVNC connection until it closes. */
export function serveVnc(socket: WebSocket, world: World): void {
  let input = Buffer.alloc(0);
  let stage: 'version' | 'security' | 'init' | 'session' = 'version';
  let fmt = DEFAULT_FORMAT;
  let wanted = false;
  let full = false;
  let sent: Scene | null = null;

  const send = (data: Buffer) => {
    if (socket.readyState === socket.OPEN) socket.send(data);
  };

  // An incremental update request is answered once the picture changes, checked twice a second.
  const timer = setInterval(update, 500);
  function update() {
    if (!wanted) return;
    const scene = sceneOf(world);
    if (!full && scene === sent) return;
    wanted = false;
    full = false;
    sent = scene;
    const header = Buffer.alloc(16);
    header.writeUInt8(0, 0); // FramebufferUpdate
    header.writeUInt16BE(1, 2); // one rectangle
    header.writeUInt16BE(WIDTH, 8);
    header.writeUInt16BE(HEIGHT, 10);
    header.writeInt32BE(0, 12); // raw
    send(Buffer.concat([header, render(scene, fmt)]));
  }

  /** Takes `n` bytes off the input, or null while they haven't all arrived. */
  function take(n: number): Buffer | null {
    if (input.length < n) return null;
    const out = input.subarray(0, n);
    input = input.subarray(n);
    return out;
  }

  /** Reads one client message; false when it needs more bytes. */
  function readMessage(): boolean {
    const type = input[0];
    const sizes: Record<number, number> = { 0: 20, 3: 10, 4: 8, 5: 6 };
    if (type === undefined) return false;
    if (type === 2) {
      if (input.length < 4) return false;
      return take(4 + 4 * input.readUInt16BE(2)) !== null;
    }
    if (type === 6) {
      if (input.length < 8) return false;
      return take(8 + input.readUInt32BE(4)) !== null;
    }
    const size = sizes[type];
    if (size === undefined) {
      socket.close(1002, `mock VNC: unknown message type ${type}`);
      return false;
    }
    const message = take(size);
    if (!message) return false;
    if (type === 0) fmt = readFormat(message.subarray(4));
    if (type === 3) {
      full ||= message.readUInt8(1) === 0;
      wanted = true;
      update();
    }
    if (type === 5 && (message.readUInt8(1) & 1) === 1 && sceneOf(world) === 'login') world.vncClick();
    return true;
  }

  socket.on('message', (data: RawData) => {
    const chunk = Array.isArray(data) ? Buffer.concat(data) : Buffer.from(data as Buffer);
    input = Buffer.concat([input, chunk]);
    for (;;) {
      if (stage === 'version') {
        if (!take(12)) return;
        send(Buffer.from([1, 1])); // one security type: None
        stage = 'security';
      } else if (stage === 'security') {
        if (!take(1)) return;
        send(Buffer.from([0, 0, 0, 0])); // SecurityResult: OK
        stage = 'init';
      } else if (stage === 'init') {
        if (!take(1)) return; // ClientInit
        const head = Buffer.alloc(4);
        head.writeUInt16BE(WIDTH, 0);
        head.writeUInt16BE(HEIGHT, 2);
        const length = Buffer.alloc(4);
        length.writeUInt32BE(NAME.length);
        send(Buffer.concat([head, packFormat(fmt), length, NAME]));
        stage = 'session';
      } else if (!readMessage()) {
        return;
      }
    }
  });
  socket.on('close', () => clearInterval(timer));
  send(Buffer.from('RFB 003.008\n'));
}

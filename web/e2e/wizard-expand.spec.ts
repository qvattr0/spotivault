// Wizard steps 3 and 4: the client's screen, larger on step 4, and Expand (web-ui.md § 3 and § 4),
// against the mock and its VNC screen (mock/vnc.ts), in a 1440 × 900 window.

import { expect, test, type Page, type WebSocket } from '@playwright/test';
import { mockControls, openPage, useScenario } from './mock.ts';

test.use({ viewport: { width: 1440, height: 900 } });

const SETTINGS = 'Spotify client · Settings';

/** The page's connections to WS /vnc, from now on. */
function vncSockets(page: Page): WebSocket[] {
  const sockets: WebSocket[] = [];
  page.on('websocket', (socket) => {
    if (socket.url().endsWith('/vnc')) sockets.push(socket);
  });
  return sockets;
}

/** Where the client's screen was clicked (RFB PointerEvent, button 1 down), in its own pixels. */
function clicksSent(socket: WebSocket): Array<{ x: number; y: number }> {
  const clicks: Array<{ x: number; y: number }> = [];
  socket.on('framesent', ({ payload }) => {
    if (typeof payload === 'string' || payload.length !== 6 || payload[0] !== 5 || (payload[1] & 1) === 0) return;
    clicks.push({ x: payload.readUInt16BE(2), y: payload.readUInt16BE(4) });
  });
  return clicks;
}

/** Records every state the view shows from now on (data-vnc-state), to catch a reconnect. */
async function watchVncStates(page: Page): Promise<() => Promise<string[]>> {
  await page.evaluate(() => {
    const view = document.querySelector('[data-vnc-state]')!;
    const seen: string[] = [view.getAttribute('data-vnc-state')!];
    (window as unknown as { vncStates: string[] }).vncStates = seen;
    new MutationObserver(() => seen.push(view.getAttribute('data-vnc-state')!)).observe(view, { attributeFilter: ['data-vnc-state'] });
  });
  return () => page.evaluate(() => (window as unknown as { vncStates: string[] }).vncStates);
}

async function openStep4(page: Page, request: Parameters<typeof useScenario>[0]) {
  await useScenario(request, 'setup', { step: 'client_settings' });
  await openPage(page, '/setup/client-settings');
  const panel = page.getByRole('region', { name: SETTINGS });
  await expect(panel.getByText('Connected', { exact: true })).toBeVisible({ timeout: 15_000 });
  return panel;
}

test.describe('step 4: the client screen', () => {
  test('is at least 700 px wide, beside the checklist, and stays in view while the list scrolls', async ({ page, request }) => {
    const panel = await openStep4(page, request);
    const screen = (await panel.locator('canvas').boundingBox())!;
    expect(screen.width).toBeGreaterThanOrEqual(700);
    expect(screen.width / screen.height).toBeCloseTo(1.6, 1);
    const row = (await page.locator('[data-row="normalization"]').boundingBox())!;
    expect(row.x).toBeGreaterThan(screen.x + screen.width);

    await page.mouse.move(1200, 600);
    await page.mouse.wheel(0, 600);
    await expect.poll(() => page.evaluate(() => document.scrollingElement!.scrollTop)).toBeGreaterThan(200);
    await expect.poll(async () => (await panel.boundingBox())!.y).toBe(24);
  });

  test('Expand grows it into a dialog at 100 % on the same connection; Escape closes it', async ({ page, request }) => {
    const sockets = vncSockets(page);
    const panel = await openStep4(page, request);
    const states = await watchVncStates(page);
    expect(sockets).toHaveLength(1);
    const clicks = clicksSent(sockets[0]);
    const expand = page.getByRole('button', { name: 'Expand' });

    await expand.click();
    const dialog = page.getByRole('dialog', { name: SETTINGS });
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute('aria-modal', 'true');
    await expect(dialog).toBeFocused();
    // As large as the window allows, never over 100 %: here the client's own 1280 × 800.
    await expect.poll(async () => (await dialog.locator('canvas').boundingBox())?.width).toBe(1280);
    expect((await dialog.locator('canvas').boundingBox())!.height).toBe(800);
    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeCloseTo((1440 - box.width) / 2, 0);
    expect(box.y).toBeCloseTo((900 - box.height) / 2, 0);

    // The page behind is dimmed, blurred, and doesn't scroll.
    const backdrop = page.locator('[data-expand-backdrop]');
    await expect.poll(() => backdrop.evaluate((element) => getComputedStyle(element).backdropFilter)).toBe('blur(12px)');
    await page.mouse.move(20, 450);
    await page.mouse.wheel(0, 600);
    expect(await page.evaluate(() => document.scrollingElement!.scrollTop)).toBe(0);

    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(expand).toBeFocused();
    await expect(backdrop).toHaveCount(0);
    await expect.poll(async () => (await panel.locator('canvas').boundingBox())?.width).toBeLessThan(1000);

    // Again: a click in the large screen lands where it was made (the screen fits its box).
    await expand.click();
    await expect.poll(async () => (await dialog.locator('canvas').boundingBox())?.width).toBe(1280);
    await dialog.locator('canvas').click({ position: { x: 100, y: 120 } });
    await expect.poll(() => clicks.at(-1)).toEqual({ x: 100, y: 120 });
    // A click on the backdrop closes it.
    await page.mouse.click(20, 450);
    await expect(dialog).toBeHidden();
    await expect(expand).toBeFocused();

    // One connection all along: never closed, none other opened, never "Connecting…".
    expect(sockets).toHaveLength(1);
    expect(sockets[0].isClosed()).toBe(false);
    expect(await states()).toEqual(['connected']);
  });

  test('the view grows from where it sits, frame by frame, as the backdrop blurs in', async ({ page, request }) => {
    const panel = await openStep4(page, request);
    const start = (await panel.boundingBox())!;
    const frames = await page.evaluate(async () => {
      const section = document.querySelector('section[aria-label="Spotify client · Settings"]')!;
      const backdrop = () => document.querySelector('[data-expand-backdrop]');
      (document.querySelector('button[aria-label="Expand"]') as HTMLButtonElement).click();
      const seen: Array<{ x: number; width: number; blur: string }> = [];
      const until = performance.now() + 450;
      while (performance.now() < until) {
        await new Promise(requestAnimationFrame);
        const { x, width } = section.getBoundingClientRect();
        seen.push({ x, width, blur: getComputedStyle(backdrop()!).backdropFilter });
      }
      return seen;
    });
    const widths = frames.map((frame) => frame.width);
    // It starts at its own size and place, and widens steadily to 1282 (the screen and borders).
    expect(widths[0]).toBeLessThan(start.width + 250);
    expect(widths.at(-1)).toBe(1282);
    expect(widths.filter((width) => width > start.width + 20 && width < 1262).length).toBeGreaterThanOrEqual(3);
    for (let i = 1; i < widths.length; i++) expect(widths[i]).toBeGreaterThanOrEqual(widths[i - 1]);
    expect(frames.some((frame) => frame.blur !== 'blur(12px)' && frame.blur !== 'blur(0px)')).toBe(true);
    expect(frames.at(-1)!.blur).toBe('blur(12px)');
  });

  test('with reduced motion it opens and closes at once', async ({ page, request }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const panel = await openStep4(page, request);
    // Read straight after each click, before a frame could pass.
    const sizes = await page.evaluate(async () => {
      const section = document.querySelector('section[aria-label="Spotify client · Settings"]')!;
      const button = section.querySelector('button')!;
      button.click();
      const open = section.getBoundingClientRect().width;
      // React renders the click's changes (the button's name) in a microtask.
      await Promise.resolve();
      button.click();
      return { open, closed: section.getBoundingClientRect().width };
    });
    expect(sizes.open).toBe(1282);
    expect(sizes.closed).toBe((await panel.boundingBox())!.width);
    await expect(page.locator('[data-expand-backdrop]')).toHaveCount(0);
  });

  // The second press of a double click on Expand lands where the button was: on the large screen
  // once it's there (at once with reduced motion; after 300 ms with motion, inside the system's
  // double-click time). It must not reach the client.
  for (const { name, reduce, gap } of [
    { name: 'a double click', reduce: false, gap: 0 },
    { name: 'with reduced motion, a double click', reduce: true, gap: 0 },
    { name: 'a slow double click (350 ms apart)', reduce: false, gap: 350 },
  ]) {
    test(`${name} on Expand opens it once, and no click reaches the client`, async ({ page, request }) => {
      if (reduce) await page.emulateMedia({ reducedMotion: 'reduce' });
      const sockets = vncSockets(page);
      await openStep4(page, request);
      const clicks = clicksSent(sockets[0]);
      const button = (await page.getByRole('button', { name: 'Expand' }).boundingBox())!;
      await page.mouse.move(button.x + button.width / 2, button.y + button.height / 2);
      await page.mouse.down();
      await page.mouse.up();
      if (gap) await page.waitForTimeout(gap);
      await page.mouse.down({ clickCount: 2 });
      await page.mouse.up({ clickCount: 2 });
      await expect(page.getByRole('dialog', { name: SETTINGS })).toBeVisible();
      await page.waitForTimeout(500);
      await expect(page.getByRole('dialog', { name: SETTINGS })).toBeVisible();
      expect(clicks).toEqual([]);
    });
  }

  test('Escape still closes it once focus falls to the page (the screen went away)', async ({ page, request }) => {
    // Keep the page's /vnc sockets, to drop them.
    // (A proxy, not a subclass: noVNC checks the socket's own prototype for its methods.)
    await page.addInitScript(() => {
      const vnc: Array<{ close(): void }> = [];
      (window as unknown as { vncSockets: typeof vnc }).vncSockets = vnc;
      window.WebSocket = new Proxy(window.WebSocket, {
        construct(Native, args: [string | URL, (string | string[])?]) {
          const socket = new Native(...args);
          if (String(args[0]).endsWith('/vnc')) vnc.push(socket);
          return socket;
        },
      });
    });
    await openStep4(page, request);
    await page.getByRole('button', { name: 'Expand' }).click();
    const dialog = page.getByRole('dialog', { name: SETTINGS });
    await expect.poll(async () => (await dialog.locator('canvas').boundingBox())?.width).toBe(1280);
    await dialog.locator('canvas').click({ position: { x: 600, y: 400 } });
    await expect.poll(() => page.evaluate(() => document.activeElement?.tagName)).toBe('CANVAS');

    // The line drops: noVNC takes its screen away, and focus falls to the page body.
    await page.evaluate(() => (window as unknown as { vncSockets: Array<{ close(): void }> }).vncSockets.forEach((socket) => socket.close()));
    await expect.poll(() => page.evaluate(() => document.activeElement === document.body)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('button', { name: 'Expand' })).toBeFocused();
  });

  test('toasts stay above the backdrop while it fades out', async ({ page, request }) => {
    await openStep4(page, request);
    await page.getByRole('button', { name: 'Expand' }).click();
    await expect(page.getByRole('dialog', { name: SETTINGS })).not.toHaveAttribute('data-moving');
    const closing = await page.evaluate(async () => {
      // The wizard's toast viewport (ToastViewport: a polite status region).
      const toasts = document.querySelector('[role="status"][aria-atomic="false"]')!;
      document.querySelector<HTMLButtonElement>('button[aria-label="Collapse"]')!.click();
      await new Promise(requestAnimationFrame);
      return {
        dialog: document.querySelector('[aria-modal="true"]') !== null,
        backdrop: document.querySelector('[data-expand-backdrop]') !== null,
        toasts: getComputedStyle(toasts).zIndex,
      };
    });
    expect(closing).toEqual({ dialog: false, backdrop: true, toasts: '50' });
  });

  test("the view's Reconnecting state shows in the dialog, and it connects there", async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'client_settings' });
    await mockControls(request).vnc(false);
    await openPage(page, '/setup/client-settings');
    await page.getByRole('button', { name: 'Expand' }).click();
    const dialog = page.getByRole('dialog', { name: SETTINGS });
    await expect(dialog.getByRole('status').filter({ hasText: 'Reconnecting…' })).toBeVisible({ timeout: 15_000 });
    await mockControls(request).vnc(true);
    await expect(dialog.getByText('Connected', { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect.poll(async () => (await dialog.locator('canvas').boundingBox())?.width).toBe(1280);
  });

  test('leaving the step while expanded leaves no backdrop or scroll lock behind', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'client_settings' });
    await openPage(page, '/setup/login');
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/client-settings$/);
    await page.getByRole('button', { name: 'Expand' }).click();
    await expect(page.getByRole('dialog', { name: SETTINGS })).toBeVisible();

    await page.goBack();
    await expect(page.getByRole('heading', { level: 1, name: 'Log in to Spotify' })).toBeVisible();
    await expect(page.locator('[data-expand-backdrop]')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe('');
  });
});

test.describe('step 4 in a 1280 × 720 window', () => {
  test.use({ viewport: { width: 1280, height: 720 } });

  test("the screen's bottom starts below the window; one scroll over the checklist brings it all in", async ({ page, request }) => {
    const panel = await openStep4(page, request);
    const before = (await panel.boundingBox())!;
    expect(before.y + before.height).toBeGreaterThan(720);
    // Over the checklist: a wheel over the screen goes to the client.
    const row = (await page.locator('[data-row="normalization"]').boundingBox())!;
    await page.mouse.move(row.x + row.width / 2, row.y + row.height / 2);
    await page.mouse.wheel(0, 400);
    await expect.poll(async () => (await panel.boundingBox())!.y).toBe(24);
    const after = (await panel.boundingBox())!;
    expect(after.y + after.height).toBeLessThanOrEqual(720);
  });

  test("a click on the dimmed page closes it, over the screen's old place too", async ({ page, request }) => {
    await openStep4(page, request);
    await page.getByRole('button', { name: 'Expand' }).click();
    const dialog = page.getByRole('dialog', { name: SETTINGS });
    await expect(dialog).not.toHaveAttribute('data-moving');
    // Left of the dialog, where the screen sat in the page.
    const box = (await dialog.boundingBox())!;
    const slot = (await page.locator('[data-lifted]:not(section)').boundingBox())!;
    const point = { x: 90, y: 600 };
    expect(point.x).toBeLessThan(box.x);
    expect(point.x).toBeGreaterThan(slot.x);
    expect(point.y).toBeGreaterThan(slot.y);
    await page.mouse.click(point.x, point.y);
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('button', { name: 'Expand' })).toBeFocused();
  });
});

test.describe('during a backup (view-only)', () => {
  test('the dialog stays view-only, and Escape closes it even from the screen', async ({ page, request }) => {
    const sockets = vncSockets(page);
    await useScenario(request, 'running');
    await openPage(page, '/setup/client-settings');
    await expect(page.getByRole('region', { name: SETTINGS }).getByText('Connected', { exact: true })).toBeVisible({ timeout: 15_000 });
    const clicks = clicksSent(sockets[0]);
    await page.getByRole('button', { name: 'Expand' }).click();
    const dialog = page.getByRole('dialog', { name: SETTINGS });
    await expect.poll(async () => (await dialog.locator('canvas').boundingBox())?.width).toBe(1280);

    await dialog.locator('canvas').click({ position: { x: 300, y: 300 } });
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    expect(clicks).toEqual([]);
  });
});

test.describe('step 3: the login screen', () => {
  test('Expand shows the code at 100 %, and a scan there logs in', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'login' });
    await openPage(page, '/setup/login');
    await expect(page.getByRole('region', { name: 'Spotify Client' }).getByText('Connected', { exact: true })).toBeVisible({ timeout: 15_000 });
    await page.getByRole('button', { name: 'Expand' }).click();
    const dialog = page.getByRole('dialog', { name: 'Spotify Client' });
    await expect.poll(async () => (await dialog.locator('canvas').boundingBox())?.width).toBe(1280);

    // A click on the code stands in for the phone's scan (mock/vnc.ts).
    await dialog.locator('canvas').click({ position: { x: 640, y: 330 } });
    await dialog.getByRole('button', { name: 'Collapse' }).click();
    await expect(page.getByText('Logged in. This step is done.')).toBeVisible({ timeout: 10_000 });
  });
});

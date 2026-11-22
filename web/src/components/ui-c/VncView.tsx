// The Spotify client's screen through noVNC (web-ui.md § Player; wizard steps 3 and 4 embed it at
// a smaller size). It connects to WS /vnc on the page's own host, and reconnects on its own.
//
//   <VncView viewOnly={recording} scale="fit" onStateChange={setVnc} retryKey={retries} />
//
// - **States** (`onStateChange`): connecting, connected, reconnecting (the line dropped, or the
//   controller said the screen isn't up yet: close code 1013), and disconnected (it gave up after
//   5 tries in a row). The Player's status strip shows them; a Retry there bumps `retryKey`. The
//   view shows the same states over itself, with its own Retry, unless `overlay={false}`.
// - **View-only** is noVNC's own: mouse and keyboard are ignored ("a guard against mistakes, not a
//   security boundary"). The Player draws the dimming and the lock itself.
// - **Scale:** `fit` scales the screen to the view; `actual` is 100 %, and the view scrolls.
// - noVNC (about 200 kB) loads when the first view mounts, not with the app.
// - **Rescale** (`ref`): `rescale()` fits the screen to the view's box at once, for a parent that
//   just changed the box's size (the wizard's Expand). noVNC does it by itself a frame later.

import { useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react';
import type RFB from '@novnc/novnc';
import { cx } from '@/lib/cx.ts';
import styles from './VncView.module.css';

export type VncState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected';

/** What a parent can ask of the view through its `ref`. */
export interface VncViewHandle {
  /** Fit the client's screen to the view's box now: the box has just changed size. */
  rescale(): void;
}

export interface VncViewProps {
  /** Ignore the mouse and keyboard (a backup is recording). */
  viewOnly?: boolean;
  /** `fit` (default) or `actual` (100 %). */
  scale?: 'fit' | 'actual';
  /** Called when the connection's state changes. */
  onStateChange?: (state: VncState) => void;
  /** Change it to connect again at once (a Retry outside the view). */
  retryKey?: number;
  /** Show the state over the view while not connected. Default true. */
  overlay?: boolean;
  /** Its accessible name. Default "Spotify client screen". */
  label?: string;
  className?: string;
  ref?: Ref<VncViewHandle>;
}

/** Tries before it gives up and shows Disconnected. */
export const VNC_TRIES = 5;
const FIRST_DELAY_MS = 1000;
const MAX_DELAY_MS = 8000;

/** WS /vnc on the page's own host: the controller in production, Vite's proxy in dev. */
export function vncUrl(location: Pick<Location, 'protocol' | 'host'> = window.location): string {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/vnc`;
}

export function VncView({
  viewOnly = false,
  scale = 'fit',
  onStateChange,
  retryKey = 0,
  overlay = true,
  label = 'Spotify client screen',
  className,
  ref,
}: VncViewProps) {
  const target = useRef<HTMLDivElement>(null);
  const rfb = useRef<RFB | null>(null);
  const [state, setState] = useState<VncState>('connecting');
  const [ownRetries, setOwnRetries] = useState(0);
  // The latest settings and callback, read when a new connection opens (refs: the connection
  // effect mustn't re-run when they change).
  const settings = useRef({ viewOnly, scale, onStateChange });
  useEffect(() => {
    settings.current = { viewOnly, scale, onStateChange };
  });

  // One connection, and the reconnects after it, for each retry.
  useEffect(() => {
    let stopped = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function report(next: VncState) {
      if (stopped) return;
      setState(next);
      settings.current.onStateChange?.(next);
    }

    async function connect() {
      const element = target.current;
      if (!element || stopped) return;
      let client: RFB;
      try {
        const { default: RFBClass } = await import('@novnc/novnc');
        if (stopped) return;
        client = new RFBClass(element, vncUrl(), { shared: true });
      } catch {
        // noVNC couldn't start here (a test without a canvas): there's no screen to show.
        report('disconnected');
        return;
      }
      rfb.current = client;
      client.viewOnly = settings.current.viewOnly;
      client.scaleViewport = settings.current.scale === 'fit';
      client.clipViewport = false;
      client.resizeSession = false;
      client.background = 'transparent';
      client.addEventListener('connect', () => {
        failures = 0;
        report('connected');
      });
      client.addEventListener('disconnect', () => {
        rfb.current = null;
        if (stopped) return;
        failures += 1;
        if (failures >= VNC_TRIES) {
          report('disconnected');
          return;
        }
        report('reconnecting');
        const delay = Math.min(MAX_DELAY_MS, FIRST_DELAY_MS * 2 ** (failures - 1));
        timer = setTimeout(() => void connect(), delay);
      });
    }

    report('connecting');
    void connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      rfb.current?.disconnect();
      rfb.current = null;
    };
  }, [retryKey, ownRetries]);

  useEffect(() => {
    if (rfb.current) rfb.current.viewOnly = viewOnly;
  }, [viewOnly, state]);

  useImperativeHandle(
    ref,
    () => ({
      rescale() {
        // Setting scaleViewport makes noVNC measure its box at once. Its own ResizeObserver waits a
        // frame, and measures with getBoundingClientRect, so a transform going on then counts.
        const client = rfb.current;
        if (client) client.scaleViewport = settings.current.scale === 'fit';
      },
    }),
    [],
  );

  useEffect(() => {
    if (rfb.current) rfb.current.scaleViewport = scale === 'fit';
  }, [scale, state]);

  return (
    <div className={cx(styles.view, viewOnly && styles.viewOnly, className)} data-vnc-state={state}>
      {/* An application: while interactive, keys and clicks go to the client's screen (noVNC). */}
      <div ref={target} className={cx(styles.screen, scale === 'actual' && styles.actual)} role="application" aria-label={label} />
      {overlay && state !== 'connected' ? (
        <div className={styles.overlay} role="status">
          {state === 'disconnected' ? (
            <>
              <span>Can&apos;t reach the client&apos;s screen.</span>
              <button type="button" className={styles.retry} onClick={() => setOwnRetries((n) => n + 1)}>
                Retry
              </button>
            </>
          ) : (
            <span>{state === 'reconnecting' ? 'Reconnecting…' : 'Connecting…'}</span>
          )}
        </div>
      ) : null}
    </div>
  );
}

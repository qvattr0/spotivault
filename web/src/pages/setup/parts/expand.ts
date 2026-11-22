// The sums and page locks behind VncPanel's Expand (use-expand.ts): where the expanded panel goes,
// the boxes on the way there, and the page's scroll lock.

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Size {
  width: number;
  height: number;
}

/** The client's screen: Xvfb's 1280 × 800 (image/rootfs/etc/s6-overlay/s6-rc.d/xserver/run). */
export const SCREEN: Size = { width: 1280, height: 800 };

/** The space kept clear round the expanded panel: the Modal's scrim padding (24). */
export const EXPANDED_MARGIN = 24;

/** The motion: about 300 ms, easing out (web-ui.md § 3, Expand). */
export const MOTION_MS = 300;

/** Easing out (cubic): fast at first, settling gently. `t` and the result go from 0 to 1. */
export function easeOut(t: number): number {
  return 1 - (1 - t) ** 3;
}

/** An element's box on the screen. */
export function boxOf(element: Element): Box {
  const { left, top, width, height } = element.getBoundingClientRect();
  return { left, top, width, height };
}

/**
 * Where the expanded panel goes in a window of `view`: the screen as large as fits, never over
 * 100 %, with the panel's `chrome` (the bar and borders) round it, centred.
 */
export function expandedBox(view: Size, chrome: Size): Box {
  const ratio = SCREEN.width / SCREEN.height;
  const screen = Math.max(
    0,
    Math.min(SCREEN.width, view.width - 2 * EXPANDED_MARGIN - chrome.width, (view.height - 2 * EXPANDED_MARGIN - chrome.height) * ratio),
  );
  const width = screen + chrome.width;
  const height = screen / ratio + chrome.height;
  return { left: Math.round((view.width - width) / 2), top: Math.round((view.height - height) / 2), width, height };
}

/** The box `progress` of the way from `from` to `to` (0 to 1). */
export function boxBetween(from: Box, to: Box, progress: number): Box {
  const at = (a: number, b: number) => a + (b - a) * progress;
  return { left: at(from.left, to.left), top: at(from.top, to.top), width: at(from.width, to.width), height: at(from.height, to.height) };
}

/** The window's own box, without its scroll bars: what `position: fixed` places in. */
export function windowSize(): Size {
  const root = document.documentElement;
  return { width: root.clientWidth || window.innerWidth, height: root.clientHeight || window.innerHeight };
}

export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Stops the page scrolling behind a modal: the window, and any box round `from` that scrolls.
 * Each keeps its scroll bar's space, so nothing on the page moves. Returns the undo.
 */
export function lockScroll(from: Element): () => void {
  const undo: Array<() => void> = [];
  const lock = (element: HTMLElement) => {
    const { overflowX, overflowY } = element.style;
    const gutter = element.style.getPropertyValue('scrollbar-gutter');
    // Its scroll bar takes room on the page now (not drawn over it): keep the room.
    if (scrollBarTakesRoom(element)) element.style.setProperty('scrollbar-gutter', 'stable');
    element.style.overflow = 'hidden';
    undo.push(() => {
      element.style.overflow = '';
      element.style.overflowX = overflowX;
      element.style.overflowY = overflowY;
      element.style.setProperty('scrollbar-gutter', gutter);
    });
  };
  const root = document.documentElement;
  for (let element = from.parentElement; element && element !== document.body && element !== root; element = element.parentElement) {
    const { overflowY } = getComputedStyle(element);
    if ((overflowY === 'auto' || overflowY === 'scroll') && element.scrollHeight > element.clientHeight) lock(element);
  }
  lock(root);
  return () => undo.reverse().forEach((step) => step());
}

function scrollBarTakesRoom(element: HTMLElement): boolean {
  if (element === document.documentElement) return window.innerWidth > element.clientWidth;
  const { borderLeftWidth, borderRightWidth } = getComputedStyle(element);
  return element.offsetWidth - element.clientWidth - (parseFloat(borderLeftWidth) || 0) - (parseFloat(borderRightWidth) || 0) > 0;
}

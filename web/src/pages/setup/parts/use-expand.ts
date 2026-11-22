// VncPanel's Expand (web-ui.md § 3 and § 4): the panel itself grows out of the page into a large
// box in the middle of the window, over a backdrop that dims and blurs the page, and shrinks back
// on Collapse.
//
// - **One connection:** the panel never moves in the React tree, so its noVNC view isn't mounted
//   again. It's lifted out with `position: fixed` (`data-lifted`); its slot keeps the space and
//   comes over the backdrop (VncPanel.module.css).
// - **Motion:** the panel's own box moves, frame by frame, from where it sat to the large box
//   (about 300 ms, easing out), and the client's screen is fitted to it in the same frame. Not a
//   scale transform: that would stretch the 36 px bar and snap back at the end, and noVNC measures
//   its box with getBoundingClientRect, transforms included.
// - The backdrop fades in with it: `--look` goes from 0 (clear) to 1 (dimmed, blurred 12 px).
// - A click or key while it moves turns it round from where it is. Its goal is measured on each
//   frame, so a window resized on the way changes where it lands.
// - **Double clicks:** the rest of a double click that opened or closed it (the second press and
//   its click) goes nowhere. Otherwise it lands where the button was: on the large screen, which
//   would send the client a click, or on the dimmed page, which would close it again.
// - **Reduced motion:** no motion. It opens and closes at once.
// - While open it's a modal dialog, by Modal's rules: focus moves in and stays in, and goes back to
//   Expand on close. Escape and Tab still work once focus has fallen to the page body (the
//   screen or its Retry went away). The page behind doesn't scroll.

import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react';
import { focusableIn } from '@/components/ui-b';
import { boxBetween, boxOf, easeOut, expandedBox, lockScroll, MOTION_MS, prefersReducedMotion, windowSize, type Box, type Size } from './expand.ts';

export type ExpandPhase = 'inline' | 'opening' | 'open' | 'closing';

export interface ExpandOptions {
  /** The panel's place on the page. It keeps the space while the panel is out. */
  slot: RefObject<HTMLElement | null>;
  /** The panel: it becomes the dialog. Its noVNC view is the `[data-vnc-state]` inside. */
  panel: RefObject<HTMLElement | null>;
  /** The Expand button: focus goes back to it when the dialog closes. */
  button: RefObject<HTMLElement | null>;
  /** The backdrop's class: how it looks, by its `--look` (0 clear, 1 dimmed and blurred). */
  backdropClass: string;
  /** Keys pressed in the client's screen go to the client (it isn't view-only), Escape too. */
  keysToScreen: boolean;
  /** The panel has just changed size: fit the client's screen to it. */
  onResize: () => void;
}

export interface Expand {
  phase: ExpandPhase;
  /** Opening or open: the panel is a modal dialog. */
  open: boolean;
  /** The button's click: Expand, or Collapse. While it moves, it turns round. */
  toggle: () => void;
  /** For the panel: Escape closes it. */
  onKeyDownCapture: (event: KeyboardEvent<HTMLElement>) => void;
  /** For the panel: Tab stays inside it. */
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
}

export function useExpand(options: ExpandOptions): Expand {
  const { slot, panel, button } = options;
  const [phase, setPhase] = useState<ExpandPhase>('inline');
  const open = phase === 'opening' || phase === 'open';
  const controls = useRef<Lift | null>(null);
  // The latest options, for the lift's own callbacks.
  const latest = useRef(options);
  useLayoutEffect(() => {
    latest.current = options;
  });

  useEffect(() => {
    if (!slot.current || !panel.current) return;
    const lift = createLift(slot.current, panel.current, { setPhase, options: () => latest.current });
    controls.current = lift;
    window.addEventListener('resize', lift.onWindowResize);
    // On the way down from the window, before anything on the page (noVNC's canvas included) hears it.
    for (const type of REPEAT_EVENTS) window.addEventListener(type, lift.swallowRepeats, true);
    return () => {
      // The step went away (Continue, Back, a link): nothing stays behind it.
      controls.current = null;
      window.removeEventListener('resize', lift.onWindowResize);
      for (const type of REPEAT_EVENTS) window.removeEventListener(type, lift.swallowRepeats, true);
      lift.destroy();
    };
  }, [slot, panel]);

  // Focus moves into the dialog as it opens, and back to Expand as it closes (Modal's rules).
  const wasOpen = useRef(false);
  useLayoutEffect(() => {
    if (open) panel.current?.focus({ preventScroll: true });
    else if (wasOpen.current) button.current?.focus({ preventScroll: true });
    wasOpen.current = open;
  }, [open, panel, button]);

  // Pull focus back if it gets out (a click on the page under the backdrop can't, but a script can).
  useEffect(() => {
    if (!open) return;
    function keepFocusInside(event: FocusEvent) {
      const dialog = panel.current;
      const target = event.target;
      if (!dialog || !(target instanceof Element) || dialog.contains(target)) return;
      if (target.closest('[aria-modal="true"], [role="menu"]')) return;
      dialog.focus({ preventScroll: true });
    }
    // When the focused control inside goes away (noVNC's screen when the line drops, the view's
    // Retry), focus falls to the page body, and keys no longer reach the panel. The document
    // hears them for it, as for Modal: Escape still closes, and Tab brings focus back in.
    function keyWithFocusLost(event: globalThis.KeyboardEvent) {
      const dialog = panel.current;
      if (!dialog || event.target !== document.body) return;
      const dialogs = document.querySelectorAll('[aria-modal="true"]');
      if (dialogs[dialogs.length - 1] !== dialog) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        controls.current?.collapse();
      } else if (event.key === 'Tab') {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
      }
    }
    document.addEventListener('focusin', keepFocusInside);
    document.addEventListener('keydown', keyWithFocusLost);
    return () => {
      document.removeEventListener('focusin', keepFocusInside);
      document.removeEventListener('keydown', keyWithFocusLost);
    };
  }, [open, panel]);

  function onKeyDownCapture(event: KeyboardEvent<HTMLElement>) {
    if (!open || event.key !== 'Escape') return;
    // In the client's screen, Escape is the client's (its menus close on it), unless it's view-only.
    const inScreen = event.target instanceof Element && event.target.closest('[role="application"]') !== null;
    if (inScreen && options.keysToScreen) return;
    // Stopped here, on the way down, so noVNC doesn't also send it to the client.
    event.preventDefault();
    event.stopPropagation();
    controls.current?.collapse();
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    const dialog = panel.current;
    if (!open || event.key !== 'Tab' || !dialog) return;
    // Wrap Tab from the last control to the first, and Shift+Tab from the first to the last.
    const items = focusableIn(dialog);
    if (items.length === 0) {
      event.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === dialog)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return {
    phase,
    open,
    toggle: () => {
      // The second click of a double click never gets here (createLift's swallowRepeats).
      if (open) controls.current?.collapse();
      else controls.current?.expand();
    },
    onKeyDownCapture,
    onKeyDown,
  };
}

/** The panel while it's out of the page. */
interface Lifted {
  /** Where the panel is drawn now. */
  box: Box;
  /** How far the backdrop has come in: 0 clear, 1 dimmed and blurred. */
  look: number;
  /** The bar and borders round the client's screen. */
  chrome: Size;
  backdrop: HTMLDivElement;
  unlockScroll: () => void;
  /** The next frame of the motion, while it moves. */
  frame: number | null;
  startedAt: number;
}

interface Lift {
  expand(): void;
  collapse(): void;
  onWindowResize(): void;
  /** For the window, on the way down: drops the rest of a double click that opened or closed it. */
  swallowRepeats(event: Event): void;
  /** Puts everything back at once: the step is going away. */
  destroy(): void;
}

const SIDES = ['left', 'top', 'width', 'height'] as const;

/** The parts of a mouse click: each carries its click count in `detail` (2 for a double click's second). */
const REPEAT_EVENTS = ['mousedown', 'mouseup', 'click', 'dblclick'] as const;

/** Lifts `panel` out of `slot` and back, moving it on the way. */
function createLift(slot: HTMLElement, panel: HTMLElement, hooks: { setPhase: (phase: ExpandPhase) => void; options: () => ExpandOptions }): Lift {
  let lifted: Lifted | null = null;
  let goal: 'open' | 'inline' = 'inline';
  // It has just opened or closed: the rest of this click's double click (`detail` 2 and up) goes
  // nowhere. The browser counts the clicks by the system's double-click time, so a new click
  // (`detail` 1) ends it.
  let repeatsSwallowed = false;

  function draw(current: Lifted) {
    for (const side of SIDES) panel.style.setProperty(side, `${current.box[side]}px`);
    current.backdrop.style.setProperty('--look', String(current.look));
    // The client's screen fits the panel's new size in this same frame.
    hooks.options().onResize();
  }

  function liftOut(): Lifted {
    // Lock first: a scroll bar going away would move the page under the panel.
    const unlockScroll = lockScroll(slot);
    const box = boxOf(panel);
    const screen = panel.querySelector('[data-vnc-state]');
    const inner = screen ? boxOf(screen) : box;
    slot.dataset.lifted = '';
    panel.dataset.lifted = '';

    const backdrop = document.createElement('div');
    backdrop.className = hooks.options().backdropClass;
    backdrop.dataset.expandBackdrop = '';
    // A click on it closes, as a click outside a menu does. It keeps focus where it is.
    backdrop.addEventListener('mousedown', (event) => event.preventDefault());
    backdrop.addEventListener('click', collapse);
    document.body.append(backdrop);

    const current: Lifted = {
      box,
      look: 0,
      chrome: { width: box.width - inner.width, height: box.height - inner.height },
      backdrop,
      unlockScroll,
      frame: null,
      startedAt: 0,
    };
    draw(current);
    return current;
  }

  function stop(current: Lifted) {
    if (current.frame !== null) cancelAnimationFrame(current.frame);
    current.frame = null;
  }

  /** Where the panel is going: the large box, or back into its slot (which keeps its place). */
  function goalBox(current: Lifted): Box {
    return goal === 'open' ? expandedBox(windowSize(), current.chrome) : boxOf(slot);
  }

  /** Moves the panel to its goal, and the backdrop to its look, from wherever they are now. */
  function move(current: Lifted) {
    const look = goal === 'open' ? 1 : 0;
    const turning = current.frame !== null;
    const elapsed = performance.now() - current.startedAt;
    stop(current);
    if (prefersReducedMotion() || typeof requestAnimationFrame !== 'function') {
      settle(current);
      return;
    }
    const from = current.box;
    const fromLook = current.look;
    // Turning round goes back as far as it came, in as long as it took.
    const duration = turning ? Math.min(MOTION_MS, Math.max(100, elapsed)) : MOTION_MS;
    const startedAt = performance.now();
    current.startedAt = startedAt;
    hooks.setPhase(goal === 'open' ? 'opening' : 'closing');
    panel.dataset.moving = '';

    const step = (now: number) => {
      const progress = easeOut(Math.min(1, Math.max(0, (now - startedAt) / duration)));
      // Measured each frame: the window can change size on the way.
      current.box = boxBetween(from, goalBox(current), progress);
      current.look = fromLook + (look - fromLook) * progress;
      draw(current);
      current.frame = progress < 1 ? requestAnimationFrame(step) : null;
      if (current.frame === null) settle(current);
    };
    current.frame = requestAnimationFrame(step);
  }

  /** The panel stays in the large box, or goes back into the page. */
  function settle(current: Lifted) {
    stop(current);
    delete panel.dataset.moving;
    if (goal === 'open') {
      current.box = goalBox(current);
      current.look = 1;
      draw(current);
      hooks.setPhase('open');
    } else {
      putBack(current);
      hooks.setPhase('inline');
      hooks.options().onResize();
    }
  }

  function putBack(current: Lifted) {
    stop(current);
    for (const side of SIDES) panel.style.removeProperty(side);
    delete panel.dataset.lifted;
    delete panel.dataset.moving;
    delete slot.dataset.lifted;
    current.backdrop.remove();
    current.unlockScroll();
    lifted = null;
  }

  function expand() {
    if (goal === 'open') return;
    goal = 'open';
    repeatsSwallowed = true;
    lifted ??= liftOut();
    move(lifted);
  }

  function collapse() {
    if (goal === 'inline' || !lifted) return;
    goal = 'inline';
    repeatsSwallowed = true;
    move(lifted);
  }

  return {
    expand,
    collapse,
    onWindowResize() {
      // While it moves, the next frame measures its goal again.
      if (!lifted || goal !== 'open' || lifted.frame !== null) return;
      lifted.box = goalBox(lifted);
      draw(lifted);
    },
    swallowRepeats(event) {
      if (!(event instanceof MouseEvent)) return;
      if (event.detail <= 1) {
        if (event.type === 'mousedown') repeatsSwallowed = false;
        return;
      }
      if (!repeatsSwallowed) return;
      event.preventDefault();
      event.stopPropagation();
    },
    destroy() {
      if (lifted) putBack(lifted);
    },
  };
}

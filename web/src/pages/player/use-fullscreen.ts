import { useEffect, useState, type RefObject } from 'react';

export interface Fullscreen {
  /** The element is shown fullscreen now. */
  active: boolean;
  toggle(): void;
}

/**
 * The browser's fullscreen for one element (web-ui.md § Toolbar: "Fullscreen: the browser's
 * fullscreen for the view. Esc leaves it."). Esc is the browser's own; `active` follows it.
 */
export function useFullscreen(ref: RefObject<HTMLElement | null>): Fullscreen {
  const [active, setActive] = useState(false);

  useEffect(() => {
    const update = () => setActive(document.fullscreenElement !== null && document.fullscreenElement === ref.current);
    document.addEventListener('fullscreenchange', update);
    return () => document.removeEventListener('fullscreenchange', update);
  }, [ref]);

  function toggle() {
    // Refused (an iframe without permission, an old browser): nothing changes.
    if (document.fullscreenElement) {
      document.exitFullscreen?.().catch(() => {});
    } else {
      ref.current?.requestFullscreen?.().catch(() => {});
    }
  }

  return { active, toggle };
}

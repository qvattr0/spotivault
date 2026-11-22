// The Library's and Albums' List / Grid choice, remembered per browser (web-ui.md § Library,
// Header: "The choice is remembered per browser"; § Albums: "remembered separately from the
// Library's"). Not part of the route (web-ui.md § Routes).
//
//   const [view, setView] = useViewMode('library');
//   <ViewSwitch value={view} onChange={setView} />
//
// It lives in localStorage. If the browser refuses storage (a private window, blocked site data),
// the choice still works on the page; it just isn't remembered.

import { useState } from 'react';
import type { ViewMode } from '@/components/ui-a';

/** The pages that remember a view, each under its own key. */
export type ViewPage = 'library' | 'albums';

const KEY = (page: ViewPage) => `spotivault.view.${page}`;

/** The remembered view, or `fallback` when there's none (or storage can't be read). */
export function readViewMode(page: ViewPage, fallback: ViewMode): ViewMode {
  try {
    const value = window.localStorage.getItem(KEY(page));
    return value === 'list' || value === 'grid' ? value : fallback;
  } catch {
    return fallback;
  }
}

function writeViewMode(page: ViewPage, mode: ViewMode): void {
  try {
    window.localStorage.setItem(KEY(page), mode);
  } catch {
    // Storage refused: the choice lasts until the page is left.
  }
}

/** The page's List / Grid choice and its setter, which remembers it. List by default, as drawn first. */
export function useViewMode(page: ViewPage, fallback: ViewMode = 'list'): [ViewMode, (mode: ViewMode) => void] {
  // A function, so storage is read once, on the first render only.
  const [mode, setMode] = useState<ViewMode>(() => readViewMode(page, fallback));
  function change(next: ViewMode) {
    setMode(next);
    writeViewMode(page, next);
  }
  return [mode, change];
}

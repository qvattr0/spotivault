import type { MouseEvent } from 'react';

/**
 * A row's click handler: a click anywhere on the row opens it, except on its own controls (the
 * toggle, the ⋯ menu and its items, Back up now, a pill that links), which do their own thing.
 */
export function rowClickHandler(onOpen?: () => void) {
  if (!onOpen) return undefined;
  return (event: MouseEvent<HTMLElement>) => {
    const target = event.target as Element;
    if (target.closest('button, a, input, label, select, textarea, [role="switch"], [role="menu"]')) return;
    onOpen();
  };
}

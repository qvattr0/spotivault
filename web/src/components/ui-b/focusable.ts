// Finding the elements keyboard users can reach, for the modal's focus trap and the menu.

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(',');

/** The elements inside `root` that Tab stops at, in order. Skips hidden ones and `tabindex="-1"`. */
export function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.tabIndex >= 0 && !el.closest('[hidden], [inert]') && el.getAttribute('aria-hidden') !== 'true',
  );
}

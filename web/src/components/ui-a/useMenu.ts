import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';

/**
 * Open/close state and keyboard handling for a menu that drops down from a button (the WAI-ARIA
 * menu button pattern). MenuButton and SplitButton use it; use it directly for a menu opened from
 * something else, such as a cover:
 *
 *   const { open, wrapperRef, triggerProps, listProps } = useMenu();
 *   <span ref={wrapperRef} className={...position: relative...}>
 *     <button {...triggerProps}>...</button>
 *     {open && <MenuList {...listProps} items={items} />}
 *   </span>
 *
 * Destructure it as above: the React lint rules read `menu.open` as touching a ref.
 *
 * It closes on Escape (focus goes back to the button), on Tab, after an item is chosen, and on a
 * click outside `wrapperRef`.
 */
export function useMenu(options: { defaultOpen?: boolean } = {}) {
  const [open, setOpen] = useState(options.defaultOpen ?? false);
  const wrapperRef = useRef<HTMLSpanElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // Which item to focus once the menu has opened. Not when it starts open (the gallery), so it
  // doesn't steal focus on load.
  const focusOnOpen = useRef<'first' | 'last' | null>(null);
  const triggerId = useId();
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    if (focusOnOpen.current) {
      const items = menuItems(listRef.current);
      (focusOnOpen.current === 'first' ? items[0] : items.at(-1))?.focus();
      focusOnOpen.current = null;
    }
    function onPointerDown(event: PointerEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  function openMenu(focus: 'first' | 'last') {
    focusOnOpen.current = focus;
    setOpen(true);
  }

  function close(returnFocus: boolean) {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }

  const triggerProps = {
    ref: triggerRef,
    id: triggerId,
    'aria-haspopup': 'menu' as const,
    'aria-expanded': open,
    'aria-controls': open ? listId : undefined,
    onClick: () => (open ? close(false) : openMenu('first')),
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        openMenu(event.key === 'ArrowDown' ? 'first' : 'last');
      }
    },
  };

  const listProps = { ref: listRef, id: listId, labelledBy: triggerId, onClose: close };

  return { open, wrapperRef, triggerProps, listProps };
}

/** The items a keyboard can reach, in order. */
export function menuItems(list: HTMLElement | null): HTMLElement[] {
  if (!list) return [];
  return [...list.querySelectorAll<HTMLElement>('[role^="menuitem"]:not(:disabled)')];
}

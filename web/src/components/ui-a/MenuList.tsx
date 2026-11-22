import type { LucideIcon } from 'lucide-react';
import { useLayoutEffect, useRef, type KeyboardEvent, type Ref, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { cx } from '@/lib/cx.ts';
import { menuItems } from './useMenu.ts';
import styles from './Menu.module.css';
import toggleStyles from './Toggle.module.css';

export interface MenuItem {
  label: string;
  /** A 16 px icon before the label: `Play` for Back up now, `Image` for Change cover… */
  icon?: LucideIcon;
  onSelect: () => void;
  /** A red label, for an action that loses something ("Stop now"). */
  danger?: boolean;
  disabled?: boolean;
  /** Makes it an on/off item with a toggle at its end ("Automatically track playlists I create"). */
  checked?: boolean;
  /** For the gallery: draws the item hovered, as Library · List does (iMmk3). */
  'data-state'?: 'hover';
}

export interface MenuListProps {
  items: MenuItem[];
  /** From useMenu().listProps. */
  id: string;
  labelledBy: string;
  onClose: (returnFocus: boolean) => void;
  ref?: Ref<HTMLDivElement>;
  /** Which edge of the button it lines up with. Default: end, as the row menus are drawn. */
  align?: 'start' | 'end';
  /** Below its button (default), or above it at the foot of the screen. */
  placement?: 'below' | 'above';
  /**
   * What it opens from (useMenu's `wrapperRef`). With it, the menu is drawn on top of the page
   * (a portal, `position: fixed`), so a parent that clips its overflow (a scrolling panel, a
   * card) can't cut it off; it follows its button on scroll, and opens the other way when there's
   * no room. Without it, it's drawn in place, under its button.
   */
  anchorRef?: RefObject<HTMLElement | null>;
}

/** Space kept between the menu and the window's edge, in px. */
const EDGE = 8;
/** Space between the button and the menu, in px (as drawn). */
const GAP = 4;

/** The open menu: a list of actions under its button (components.md § Menu). Arrow keys move. */
export function MenuList({ items, id, labelledBy, onClose, ref, align = 'end', placement = 'below', anchorRef }: MenuListProps) {
  const own = useRef<HTMLDivElement | null>(null);

  // On top of the page: place the menu at its button, before the browser paints, and again when
  // anything scrolls or the window changes size. Written to the element's style directly: it's
  // only position, and it changes on every scroll.
  useLayoutEffect(() => {
    const list = own.current;
    if (!anchorRef || !list) return;
    function place() {
      const anchor = anchorRef?.current?.getBoundingClientRect();
      if (!anchor || !list) return;
      const { offsetWidth: width, offsetHeight: height } = list;
      const fitsBelow = anchor.bottom + GAP + height <= window.innerHeight - EDGE;
      const fitsAbove = anchor.top - GAP - height >= EDGE;
      const up = placement === 'above' ? fitsAbove || !fitsBelow : !fitsBelow && fitsAbove;
      const left = align === 'end' ? anchor.right - width : anchor.left;
      list.dataset.placement = up ? 'above' : 'below';
      list.style.top = `${up ? anchor.top - GAP - height : anchor.bottom + GAP}px`;
      list.style.left = `${Math.max(EDGE, Math.min(left, window.innerWidth - width - EDGE))}px`;
    }
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [anchorRef, align, placement]);

  /** Both refs: useMenu's (focus, outside clicks) and this one (placing). */
  function setRefs(node: HTMLDivElement | null) {
    own.current = node;
    if (typeof ref === 'function') ref(node);
    else if (ref) ref.current = node;
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const all = menuItems(event.currentTarget);
    const i = all.indexOf(document.activeElement as HTMLElement);
    const next = {
      ArrowDown: all[(i + 1) % all.length],
      ArrowUp: all[(i - 1 + all.length) % all.length],
      Home: all[0],
      End: all.at(-1),
    }[event.key];
    if (next) {
      event.preventDefault();
      next.focus();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      onClose(true);
    } else if (event.key === 'Tab') {
      // Focus goes back to the button first, so Tab moves on from there: the menu sits at the end
      // of the page (a portal), where Tab would leave the page.
      onClose(true);
    }
  }

  const menu = (
    <div
      ref={setRefs}
      id={id}
      role="menu"
      aria-labelledby={labelledBy}
      className={cx(
        styles.menu,
        anchorRef ? styles.floating : [align === 'end' ? styles.alignEnd : styles.alignStart, placement === 'above' && styles.above].filter(Boolean).join(' '),
      )}
      onKeyDown={onKeyDown}
    >
      {items.map((item) => {
        const Icon = item.icon;
        const checkable = item.checked !== undefined;
        return (
          <button
            key={item.label}
            type="button"
            role={checkable ? 'menuitemcheckbox' : 'menuitem'}
            aria-checked={checkable ? item.checked : undefined}
            tabIndex={-1}
            disabled={item.disabled}
            data-state={item['data-state']}
            className={cx(styles.item, item.danger && styles.danger)}
            onClick={() => {
              onClose(true);
              item.onSelect();
            }}
          >
            {Icon && <Icon size={16} />}
            <span className={styles.label}>{item.label}</span>
            {checkable && (
              <span className={cx(toggleStyles.toggle, item.checked && toggleStyles.on, styles.itemToggle)}>
                <span className={toggleStyles.knob} />
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
  return anchorRef ? createPortal(menu, document.body) : menu;
}

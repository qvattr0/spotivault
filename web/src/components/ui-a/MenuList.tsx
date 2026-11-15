import type { LucideIcon } from 'lucide-react';
import type { KeyboardEvent, Ref } from 'react';
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
}

/** The open menu: a list of actions under its button (components.md § Menu). Arrow keys move. */
export function MenuList({ items, id, labelledBy, onClose, ref, align = 'end', placement = 'below' }: MenuListProps) {
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
      onClose(false);
    }
  }

  return (
    <div
      ref={ref}
      id={id}
      role="menu"
      aria-labelledby={labelledBy}
      className={cx(
        styles.menu,
        align === 'end' ? styles.alignEnd : styles.alignStart,
        placement === 'above' && styles.above,
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
}

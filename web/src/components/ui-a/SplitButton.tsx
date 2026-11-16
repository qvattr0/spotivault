import { ChevronDown, Square, type LucideIcon } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import { MenuList, type MenuItem } from './MenuList.tsx';
import { useMenu } from './useMenu.ts';
import menuStyles from './Menu.module.css';
import styles from './SplitButton.module.css';

export interface SplitButtonProps {
  /** The main action: "Stop after this track". */
  label: string;
  onClick: () => void;
  /** The arrow's accessible name: "More ways to stop". */
  menuLabel: string;
  /** What the arrow opens: [{ label: 'Stop now', danger: true, onSelect }]. */
  items: MenuItem[];
  /** Below the button (default), or above it: the global bottom bar is at the foot of the screen. */
  menuPlacement?: 'below' | 'above';
  /** Default: `Square`, the stop icon. */
  icon?: LucideIcon;
  /** Disables both halves. */
  disabled?: boolean;
  /** Disables the main action only; the arrow's menu still opens. */
  mainDisabled?: boolean;
  /** For the gallery: start with the menu open. */
  defaultOpen?: boolean;
  /** Passed to the main button, for the gallery's states. */
  'data-state'?: string;
  className?: string;
}

/**
 * The run's Stop button (components.md § Buttons, Button/Split): the main action, and an arrow
 * that opens a menu with the others. web-ui.md § Running: "Stop after this track" is the main
 * action; "Stop now" comes from the arrow, and the page confirms it first.
 */
export function SplitButton({
  label,
  onClick,
  menuLabel,
  items,
  icon: Icon = Square,
  menuPlacement = 'below',
  disabled = false,
  mainDisabled = false,
  defaultOpen,
  'data-state': dataState,
  className,
}: SplitButtonProps) {
  const { open, wrapperRef, triggerProps, listProps } = useMenu({ defaultOpen });
  return (
    <span ref={wrapperRef} className={cx(menuStyles.wrapper, styles.split, className)}>
      <button type="button" className={styles.main} disabled={disabled || mainDisabled} onClick={onClick} data-state={dataState}>
        <Icon size={14} />
        {label}
      </button>
      <span className={styles.divider} />
      <button type="button" className={styles.arrow} disabled={disabled} aria-label={menuLabel} {...triggerProps}>
        <ChevronDown size={16} />
      </button>
      {open && <MenuList {...listProps} items={items} placement={menuPlacement} />}
    </span>
  );
}

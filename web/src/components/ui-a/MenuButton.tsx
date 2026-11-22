import { Ellipsis, type LucideIcon } from 'lucide-react';
import { IconButton } from './IconButton.tsx';
import { MenuList, type MenuItem } from './MenuList.tsx';
import { useMenu } from './useMenu.ts';
import styles from './Menu.module.css';

export interface MenuButtonProps {
  /** The button's accessible name: "Options for Late Night Drive". */
  label: string;
  items: MenuItem[];
  /** Default: `Ellipsis`, the ⋯ of a row menu. */
  icon?: LucideIcon;
  /** Which edge the menu lines up with. Default: end. */
  align?: 'start' | 'end';
  /** Below the button (default), or above it at the foot of the screen. */
  placement?: 'below' | 'above';
  /** For the gallery: start with the menu open. */
  defaultOpen?: boolean;
}

/**
 * An icon button that opens a menu: the ⋯ row menus in the Library and Albums, and the
 * Library header's options menu. The menu needs room below it: no ancestor may clip overflow.
 */
export function MenuButton({
  label,
  items,
  icon = Ellipsis,
  align = 'end',
  placement = 'below',
  defaultOpen,
}: MenuButtonProps) {
  const { open, wrapperRef, triggerProps, listProps } = useMenu({ defaultOpen });
  return (
    <span ref={wrapperRef} className={styles.wrapper}>
      <IconButton icon={icon} label={label} {...triggerProps} />
      {open && <MenuList {...listProps} items={items} align={align} placement={placement} />}
    </span>
  );
}

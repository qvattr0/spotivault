import type { LucideIcon } from 'lucide-react';
import type { ComponentProps, MouseEvent } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './IconButton.module.css';

export interface IconButtonProps extends ComponentProps<'button'> {
  /** The Lucide icon: `Ellipsis` (the default in the drawing), `Plus`, `X`, ... */
  icon: LucideIcon;
  /** What it does, for screen readers and as its accessible name: "Close", "Add playlists". */
  label: string;
  /** The Library header's + button: a bg-highlight fill and a white icon. */
  filled?: boolean;
}

/**
 * A round 36 px button with only an icon (components.md § Buttons, Button/Icon). It has no visible
 * text, so `label` is required. Pair it with ui-b's tooltip where the icon isn't obvious.
 * `aria-disabled` keeps it focusable for that tooltip and ignores its clicks.
 */
export function IconButton({
  icon: Icon,
  label,
  filled = false,
  className,
  type = 'button',
  onClick,
  'aria-disabled': ariaDisabled,
  ...rest
}: IconButtonProps) {
  const inert = ariaDisabled === true || ariaDisabled === 'true';
  return (
    <button
      {...rest}
      type={type}
      aria-label={label}
      aria-disabled={inert || undefined}
      className={cx(styles.iconButton, filled && styles.filled, className)}
      onClick={inert ? ignoreClick : onClick}
    >
      <Icon size={20} />
    </button>
  );
}

function ignoreClick(event: MouseEvent) {
  event.preventDefault();
}

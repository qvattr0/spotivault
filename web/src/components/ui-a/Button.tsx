import type { ComponentProps, MouseEvent } from 'react';
import { ButtonContent, buttonClassName, type ButtonLook } from './button-parts.tsx';

export interface ButtonProps extends ComponentProps<'button'>, ButtonLook {
  /** Waiting for the server: a spinner replaces the leading icon, and clicks are ignored. */
  busy?: boolean;
}

/**
 * A pill button: `primary` (Run now), `secondary` (Re-check), `tertiary` (Change schedule),
 * `tertiary-danger` (Disconnect) or `danger` (Stop now). components.md § Buttons.
 *
 * `disabled` greys it out and takes it out of the tab order. `aria-disabled` greys it out too but
 * keeps it focusable, for a button that explains itself in a tooltip ("Not available while a
 * backup is recording"); its clicks are ignored.
 */
export function Button({
  variant,
  size = 'md',
  icon,
  trailingIcon,
  busy = false,
  className,
  type = 'button',
  onClick,
  children,
  'aria-disabled': ariaDisabled,
  ...rest
}: ButtonProps) {
  const inert = busy || ariaDisabled === true || ariaDisabled === 'true';
  return (
    <button
      {...rest}
      type={type}
      className={buttonClassName(variant, size, className)}
      aria-disabled={inert || undefined}
      aria-busy={busy || undefined}
      onClick={inert ? ignoreClick : onClick}
    >
      <ButtonContent variant={variant} size={size} icon={icon} trailingIcon={trailingIcon} busy={busy}>
        {children}
      </ButtonContent>
    </button>
  );
}

function ignoreClick(event: MouseEvent) {
  event.preventDefault();
}

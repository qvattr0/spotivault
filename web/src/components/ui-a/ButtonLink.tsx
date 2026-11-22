import type { ComponentProps } from 'react';
import { Link } from 'react-router';
import { ButtonContent, buttonClassName, type ButtonLook } from './button-parts.tsx';

type AnchorProps = Omit<ComponentProps<'a'>, 'href'>;

export type ButtonLinkProps = AnchorProps &
  ButtonLook &
  (
    | { /** A page of this app: '/schedule'. */ to: string; href?: never }
    | { /** Another site. It opens in a new tab. */ href: string; to?: never }
  );

/**
 * A link that looks like a button: "Change schedule" (to Schedule), "View in History",
 * "Open developer dashboard" (another site). Same variants as Button.
 */
export function ButtonLink({
  variant,
  size = 'md',
  icon,
  trailingIcon,
  className,
  to,
  href,
  children,
  ...rest
}: ButtonLinkProps) {
  const content = (
    <ButtonContent variant={variant} size={size} icon={icon} trailingIcon={trailingIcon}>
      {children}
    </ButtonContent>
  );
  const classes = buttonClassName(variant, size, className);

  if (to !== undefined) {
    return (
      <Link {...rest} to={to} className={classes}>
        {content}
      </Link>
    );
  }
  return (
    <a {...rest} href={href} className={classes} target="_blank" rel="noreferrer">
      {content}
      {/* The space sits outside the span so the accessible name keeps it. */}{' '}
      <span className="visually-hidden">(opens in a new tab)</span>
    </a>
  );
}

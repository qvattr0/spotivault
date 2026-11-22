import { LoaderCircle, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './Button.module.css';

// What Button and ButtonLink share: the class names and the inside (icon, label, icon).

export type ButtonVariant = 'primary' | 'secondary' | 'tertiary' | 'tertiary-danger' | 'danger';

/** The options both Button and ButtonLink take. */
export interface ButtonLook {
  /** components.md § Buttons. `tertiary-danger` is the red text action ("Disconnect", Settings). */
  variant: ButtonVariant;
  /** `sm` is the primary button in a modal footer ("Done"): padding 10 24, label 14. Primary only. */
  size?: 'md' | 'sm';
  /** A leading icon, off by default in the drawing: `RefreshCw` on "Re-check". */
  icon?: LucideIcon;
  /** A trailing icon: `ChevronRight` on a tertiary button ("Change schedule"). */
  trailingIcon?: LucideIcon;
}

const CLASS: Record<ButtonVariant, string | undefined> = {
  primary: styles.primary,
  secondary: styles.secondary,
  tertiary: styles.tertiary,
  'tertiary-danger': styles.tertiaryDanger,
  danger: styles.danger,
};

export function buttonClassName(variant: ButtonVariant, size: 'md' | 'sm' = 'md', className?: string): string {
  return cx(styles.button, CLASS[variant], size === 'sm' && styles.sm, className);
}

/** Icon sizes from components.md: 18 on Primary, 16 on the others. */
function iconSize(variant: ButtonVariant, size: 'md' | 'sm'): number {
  return variant === 'primary' && size === 'md' ? 18 : 16;
}

interface ButtonContentProps extends ButtonLook {
  busy?: boolean;
  children: ReactNode;
}

/** The inside of a button: a spinner in place of the leading icon while busy. */
export function ButtonContent({
  variant,
  size = 'md',
  icon: Icon,
  trailingIcon: Trailing,
  busy,
  children,
}: ButtonContentProps) {
  const px = iconSize(variant, size);
  return (
    <>
      {busy ? <LoaderCircle size={px} className={styles.spinner} /> : Icon && <Icon size={px} />}
      <span>{children}</span>
      {Trailing && <Trailing size={px} />}
    </>
  );
}

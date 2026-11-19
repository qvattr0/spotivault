import { cx } from '@/lib/cx.ts';
import { Logo } from './Logo.tsx';
import styles from './Brand.module.css';

export interface BrandProps {
  /** `sidebar`: "spotivault" at 19 px. `wizard`: "spotivault setup" at 18 px. */
  variant: 'sidebar' | 'wizard';
  className?: string;
}

/** Logo/Mark 32 and the wordmark, as the sidebar and the setup wizard's header show them. */
export function Brand({ variant, className }: BrandProps) {
  return (
    <span className={cx(styles.brand, styles[variant], className)}>
      <Logo size={32} />
      <span>{variant === 'wizard' ? 'spotivault setup' : 'spotivault'}</span>
    </span>
  );
}

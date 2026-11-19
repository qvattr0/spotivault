import type { ComponentProps } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './Chip.module.css';

export interface ChipProps extends ComponentProps<'button'> {
  /** On: the white chip. */
  selected: boolean;
  /** `sm` is the compact chip row of History · Logs. */
  size?: 'md' | 'sm';
}

/**
 * A filter chip that turns on and off by itself (components.md § Filter chip): the Logs source
 * and level filters, where several can be on. For a one-of-several choice (All · Tracked · …,
 * the format) use ChipGroup; for History's tabs, ChipLink.
 */
export function Chip({ selected, size = 'md', className, type = 'button', ...rest }: ChipProps) {
  return (
    <button
      {...rest}
      type={type}
      aria-pressed={selected}
      className={cx(styles.chip, selected && styles.on, size === 'sm' && styles.sm, className)}
    />
  );
}

import type { ComponentProps } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './Toggle.module.css';

export interface ToggleProps extends Omit<ComponentProps<'button'>, 'onChange'> {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /**
   * Its accessible name: "Track Late Night Drive". Leave it out when a visible label names it
   * through `aria-labelledby` (a Settings row's title).
   */
  label?: string;
}

/**
 * An on/off switch (components.md § Toggle). A button with the switch role: click, Space or Enter
 * flips it, and `onChange` gets the new value.
 */
export function Toggle({ checked, onChange, label, className, type = 'button', ...rest }: ToggleProps) {
  return (
    <button
      {...rest}
      type={type}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={cx(styles.toggle, checked && styles.on, className)}
      onClick={() => onChange(!checked)}
    >
      <span className={styles.knob} />
    </button>
  );
}

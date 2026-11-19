import { Check } from 'lucide-react';
import type { ComponentProps, ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './Checkbox.module.css';

export interface CheckboxProps extends Omit<ComponentProps<'input'>, 'type' | 'checked' | 'onChange'> {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** The row's text: "I understand". Without it, pass `aria-label` (a table cell's checkbox). */
  label?: ReactNode;
}

/** A checkbox row (components.md § Checkbox row): the box and its label. Clicking either toggles it. */
export function Checkbox({ checked, onChange, label, className, disabled, ...rest }: CheckboxProps) {
  return (
    <label className={cx(styles.row, label === undefined && styles.bare, disabled && styles.disabled, className)}>
      <input
        {...rest}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        className={styles.input}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className={cx(styles.box, checked && styles.on)} aria-hidden="true">
        {checked && <Check size={14} />}
      </span>
      {label !== undefined && <span>{label}</span>}
    </label>
  );
}

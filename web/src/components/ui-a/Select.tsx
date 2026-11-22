import { ChevronDown } from 'lucide-react';
import type { ComponentProps } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './Select.module.css';

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
}

export interface SelectProps<T extends string = string> extends Omit<
  ComponentProps<'select'>,
  'value' | 'onChange' | 'prefix'
> {
  /** Its accessible name: "Sort", "Run". */
  label: string;
  options: SelectOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** `quiet` is the sort ("Recently backed up ⌄"); `boxed` the Logs run filter ("Run: All ⌄"). */
  variant?: 'quiet' | 'boxed';
  /** Visible text before the choice: "Run:". */
  prefix?: string;
  /** For the gallery: 'hover' or 'focus' draws that state. */
  'data-state'?: string;
}

/** A drop-down choice, on the browser's own <select>, styled as the screens draw it closed. */
export function Select<T extends string = string>({
  label,
  options,
  value,
  onChange,
  variant = 'quiet',
  prefix,
  className,
  disabled,
  'data-state': dataState,
  ...rest
}: SelectProps<T>) {
  const current = options.find((option) => option.value === value);
  return (
    <span className={cx(styles.select, styles[variant], disabled && styles.disabled, className)} data-state={dataState}>
      {/* What the closed box shows. The <select> below says the same to screen readers. */}
      <span aria-hidden="true">
        {prefix && `${prefix} `}
        {current?.label}
      </span>
      <ChevronDown size={16} />
      <select
        {...rest}
        aria-label={label}
        value={value}
        disabled={disabled}
        className={styles.native}
        onChange={(event) => onChange(event.target.value as T)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </span>
  );
}

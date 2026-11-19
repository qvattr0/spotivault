import type { LucideIcon } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import { onRadioKeyDown } from './radio-keys.ts';
import styles from './SegmentedControl.module.css';

export interface SegmentOption<T extends string = string> {
  value: T;
  /** The segment's text, or its accessible name when it shows an icon. */
  label: string;
  /** Show this 16 px icon instead of the label: `List`, `LayoutGrid`. */
  icon?: LucideIcon;
  /** For the gallery only: draw this segment hovered or focused. */
  state?: 'hover' | 'focus';
}

export interface SegmentedControlProps<T extends string = string> {
  /** The group's accessible name: "View", "Scale". */
  label: string;
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/**
 * Two or three segments in a pill track, one of them chosen: the List / Grid view switch
 * (components.md § View switch) and the Player's Fit / 100% scale. A radio group: one Tab stop,
 * arrow keys move.
 */
export function SegmentedControl<T extends string = string>({
  label,
  options,
  value,
  onChange,
  className,
}: SegmentedControlProps<T>) {
  const values = options.map((option) => option.value);
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cx(styles.track, className)}
      onKeyDown={(event) => onRadioKeyDown(event, values, value, onChange)}
    >
      {options.map((option, i) => {
        const selected = option.value === value;
        const tabbable = selected || (!values.includes(value) && i === 0);
        const Icon = option.icon;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={Icon ? option.label : undefined}
            tabIndex={tabbable ? 0 : -1}
            data-state={option.state}
            className={cx(styles.segment, Icon ? styles.icon : styles.text, selected && styles.selected)}
            onClick={() => onChange(option.value)}
          >
            {Icon ? <Icon size={16} /> : option.label}
          </button>
        );
      })}
    </div>
  );
}

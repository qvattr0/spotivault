import { cx } from '@/lib/cx.ts';
import { onRadioKeyDown } from './radio-keys.ts';
import styles from './Chip.module.css';

export interface ChipOption<T extends string = string> {
  value: T;
  label: string;
}

export interface ChipGroupProps<T extends string = string> {
  /** The group's accessible name: "Filter", "Format". */
  label: string;
  options: ChipOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: 'md' | 'sm';
  className?: string;
}

/**
 * Chips where exactly one is on (components.md § Filter chip): the Library's All · Tracked · …,
 * Albums' and History's filters, and the format in Settings › Recording ("a one-of-three choice").
 * A radio group: one Tab stop, arrow keys move.
 */
export function ChipGroup<T extends string = string>({
  label,
  options,
  value,
  onChange,
  size = 'md',
  className,
}: ChipGroupProps<T>) {
  const values = options.map((option) => option.value);
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cx(styles.group, className)}
      onKeyDown={(event) => onRadioKeyDown(event, values, value, onChange)}
    >
      {options.map((option, i) => {
        const selected = option.value === value;
        // Only the chosen chip is in the tab order; the first one if none is chosen.
        const tabbable = selected || (!values.includes(value) && i === 0);
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={tabbable ? 0 : -1}
            className={cx(styles.chip, selected && styles.on, size === 'sm' && styles.sm)}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

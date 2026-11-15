import { Search, X } from 'lucide-react';
import type { ComponentProps, KeyboardEvent } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './SearchInput.module.css';

export interface SearchInputProps extends Omit<ComponentProps<'input'>, 'type'> {
  /** Its accessible name. Default: the placeholder ("Search in Library"). */
  label?: string;
  /** Empties the search. With it, a clear button shows while there's text, and Escape clears too. */
  onClear?: () => void;
  /** For the gallery: 'hover' or 'focus' draws that state on the box. */
  'data-state'?: string;
}

/** The round search box of the Library, Albums, the + modals and Logs (components.md § Search input). */
export function SearchInput({
  label,
  onClear,
  className,
  disabled,
  value,
  onKeyDown,
  'data-state': dataState,
  ...rest
}: SearchInputProps) {
  const hasText = value !== undefined && String(value) !== '';

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape' && onClear && hasText) {
      event.preventDefault();
      onClear();
    }
    onKeyDown?.(event);
  }

  return (
    <div className={cx(styles.box, disabled && styles.disabled, className)} data-state={dataState}>
      <Search size={18} />
      <input
        {...rest}
        type="search"
        value={value}
        disabled={disabled}
        aria-label={label ?? rest.placeholder}
        className={styles.input}
        onKeyDown={handleKeyDown}
      />
      {onClear && hasText && !disabled && (
        <button type="button" className={styles.clear} aria-label="Clear search" onClick={onClear}>
          <X size={16} />
        </button>
      )}
    </div>
  );
}

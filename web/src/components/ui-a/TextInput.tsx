import { useId, type ComponentProps, type ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './TextInput.module.css';

export interface TextInputProps extends Omit<ComponentProps<'input'>, 'prefix'> {
  /** A visible label above the box ("Layout"). Without one, pass `aria-label`. */
  label?: string;
  /** A line under the box. */
  hint?: ReactNode;
  /** Replaces the hint, in red, and marks the field invalid (web-ui.md § Files: "An error replaces the hint"). */
  error?: string;
  /** Mono 12 for URIs, Client IDs and pasted URLs (components.md § Text input, Filled). */
  mono?: boolean;
  /** Fixed text before the value, in text-muted: "Music/". */
  prefix?: string;
  /** Fixed text after the value: ".m4a". */
  suffix?: string;
  /** Something at the box's right end: the Edit layout field's "Valid" check. */
  end?: ReactNode;
  /** For the gallery: 'hover' or 'focus' draws that state on the box. */
  'data-state'?: string;
}

/** A one-line text field (components.md § Text input). It fills its container's width. */
export function TextInput({
  label,
  hint,
  error,
  mono = false,
  prefix,
  suffix,
  end,
  className,
  disabled,
  id,
  'data-state': dataState,
  ...rest
}: TextInputProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const noteId = `${inputId}-note`;
  const note = error ?? hint;

  return (
    <div className={cx(styles.field, className)}>
      {label && (
        <label htmlFor={inputId} className={styles.label}>
          {label}
        </label>
      )}
      <div
        className={cx(
          styles.box,
          mono && styles.mono,
          error !== undefined && styles.invalid,
          disabled && styles.disabled,
        )}
        data-state={dataState}
      >
        {prefix && <span className={styles.affix}>{prefix}</span>}
        <input
          {...rest}
          id={inputId}
          disabled={disabled}
          className={cx(styles.input, suffix !== undefined && styles.hugs)}
          aria-invalid={error !== undefined || undefined}
          aria-describedby={note !== undefined ? noteId : undefined}
        />
        {suffix && <span className={styles.affix}>{suffix}</span>}
        {end && <span className={styles.end}>{end}</span>}
      </div>
      {note !== undefined && (
        <p id={noteId} className={error !== undefined ? styles.error : styles.hint}>
          {note}
        </p>
      )}
    </div>
  );
}

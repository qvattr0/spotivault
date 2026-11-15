import { ArrowDownToLine } from 'lucide-react';
import type { ComponentProps } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './PlayButton.module.css';

export interface PlayButtonProps extends ComponentProps<'button'> {
  /** Its accessible name. "Back up now" in the Library; "Record now" for an album. */
  label?: string;
}

/**
 * The round green "Back up now" button (components.md § Buttons, Button/Play), in the place of
 * the client's play button: on a hovered card or row, and in a detail header.
 */
export function PlayButton({ label = 'Back up now', className, type = 'button', ...rest }: PlayButtonProps) {
  return (
    <button {...rest} type={type} aria-label={label} className={cx(styles.play, className)}>
      <ArrowDownToLine size={22} />
    </button>
  );
}

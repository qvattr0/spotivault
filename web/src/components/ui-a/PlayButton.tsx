import { ArrowDownToLine } from 'lucide-react';
import type { ComponentProps } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './PlayButton.module.css';

export interface PlayButtonProps extends ComponentProps<'button'> {
  /** Its accessible name. "Back up now" in the Library; "Record now" for an album. */
  label?: string;
  /**
   * `lg` is the detail header's, 56 px (Library · Detail, l9Wn7L). Default 48, as on a card. `sm`,
   * 32 px, sits over a list row's 44 px cover (ours: the drawings put a 48 there, wider than the art).
   */
  size?: 'sm' | 'md' | 'lg';
}

/**
 * The round green "Back up now" button (components.md § Buttons, Button/Play), in the place of
 * the client's play button: on a hovered card or row, and in a detail header.
 */
const ICON_SIZE = { sm: 16, md: 22, lg: 26 } as const;

export function PlayButton({ label = 'Back up now', size = 'md', className, type = 'button', ...rest }: PlayButtonProps) {
  return (
    <button {...rest} type={type} aria-label={label} className={cx(styles.play, size === 'lg' && styles.lg, size === 'sm' && styles.sm, className)}>
      <ArrowDownToLine size={ICON_SIZE[size]} />
    </button>
  );
}

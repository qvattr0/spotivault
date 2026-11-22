import { useId, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './Disclosure.module.css';

export interface DisclosureProps {
  /** "More formats". */
  label: string;
  /**
   * Beside the label (`inline`): "FLAC, WAV · no benefit, the source is lossy". Under it (`row`):
   * "FLAC and WAV: no benefit, the source is lossy (Ogg Vorbis 320). Bigger files, same quality."
   */
  hint?: ReactNode;
  /**
   * `inline`: wizard step 6 (Mj5zE), a chevron, the label and the hint on one line. `row`: a
   * Settings row (t6RqK), the label and hint at the left and a chevron at the right.
   */
  variant?: 'inline' | 'row';
  /** Starts open. It opens by itself, too, when what it holds is chosen (pass `open`). */
  defaultOpen?: boolean;
  /** Controls it from outside, with onOpenChange. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** What it shows when open: FLAC and WAV. */
  children: ReactNode;
  className?: string;
}

/**
 * A collapsed section: "More formats", which holds FLAC and WAV (web-ui.md § 6 and Settings ›
 * Recording). A button with aria-expanded; the content is in the page only while open.
 */
export function Disclosure({
  label,
  hint,
  variant = 'inline',
  defaultOpen = false,
  open: controlled,
  onOpenChange,
  children,
  className,
}: DisclosureProps) {
  const [own, setOwn] = useState(defaultOpen);
  const open = controlled ?? own;
  const id = useId();
  function toggle() {
    setOwn(!open);
    onOpenChange?.(!open);
  }
  const Chevron = variant === 'row' ? ChevronDown : ChevronRight;
  return (
    <div className={cx(styles.disclosure, styles[variant], open && styles.open, className)}>
      <button type="button" className={styles.trigger} aria-expanded={open} aria-controls={id} onClick={toggle}>
        {variant === 'inline' ? <Chevron size={16} className={styles.chevron} aria-hidden /> : null}
        <span className={styles.texts}>
          <span className={styles.label}>{label}</span>
          {hint ? <span className={styles.hint}>{hint}</span> : null}
        </span>
        {variant === 'row' ? <Chevron size={18} className={styles.chevron} aria-hidden /> : null}
      </button>
      {open ? (
        <div id={id} className={styles.content}>
          {children}
        </div>
      ) : null}
    </div>
  );
}

import type { HTMLAttributes, ReactNode, Ref } from 'react';
import { X } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './Modal.module.css';

export interface ModalBoxProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  /** The heading's id, for the dialog's aria-labelledby. */
  titleId?: string;
  onClose: () => void;
  footer?: ReactNode;
  /** In px. 560 as drawn. */
  width?: number;
  ref?: Ref<HTMLDivElement>;
}

/**
 * The modal's box: header with the title and ×, body, footer. Modal shows it over the scrim and
 * looks after focus; on its own it draws the box in place (the gallery). Pages use Modal.
 */
export function ModalBox({ title, titleId, onClose, footer, width = 560, children, className, style, ref, ...rest }: ModalBoxProps) {
  return (
    <div ref={ref} className={cx(styles.dialog, className)} style={{ width, ...style }} {...rest}>
      <div className={styles.header}>
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        <button type="button" className={styles.close} onClick={onClose} aria-label="Close">
          <X size={20} aria-hidden />
        </button>
      </div>
      <div className={styles.body}>{children}</div>
      {footer ? <div className={styles.footer}>{footer}</div> : null}
    </div>
  );
}

import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './TooltipBubble.module.css';

export interface TooltipBubbleProps {
  children: ReactNode;
  id?: string;
  hidden?: boolean;
  className?: string;
}

/**
 * The tooltip's box on its own (components.md § Week-grid cell, the hover tooltip `SxrJu`), for
 * places that position it themselves, like the schedule grid. Elsewhere use <Tooltip>.
 */
export function TooltipBubble({ children, id, hidden, className }: TooltipBubbleProps) {
  return (
    <span id={id} role="tooltip" hidden={hidden} className={cx(styles.bubble, className)}>
      {children}
    </span>
  );
}

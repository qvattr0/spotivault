import { cloneElement, useId, useState, type ReactElement } from 'react';
import { cx } from '@/lib/cx.ts';
import { TooltipBubble } from './TooltipBubble.tsx';
import styles from './Tooltip.module.css';

export interface TooltipProps {
  /** The tooltip's text: "Not available while a backup is recording". */
  label: string;
  /** One focusable element: a button, a link. It gets `aria-describedby`. */
  children: ReactElement<{ 'aria-describedby'?: string }>;
  /** Below by default, as on the Player's toolbar (jh5YJ). */
  placement?: 'bottom' | 'top';
  /** Which edge it lines up with. 'end' keeps it inside the page at the right edge. */
  align?: 'center' | 'start' | 'end';
  className?: string;
}

/**
 * Shows a short label while the pointer is over its child or the child has keyboard focus.
 * Escape hides it. Screen readers get the label as the child's description.
 *
 * A disabled button gets no focus, so keyboard users never see its tooltip: use `aria-disabled`
 * on a button that needs one (the Player's Restart during a run).
 */
export function Tooltip({ label, children, placement = 'bottom', align = 'center', className }: TooltipProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const describedBy = [children.props['aria-describedby'], id].filter(Boolean).join(' ');

  return (
    <span
      className={cx(styles.anchor, className)}
      onPointerEnter={() => setOpen(true)}
      onPointerLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && open) {
          event.stopPropagation();
          setOpen(false);
        }
      }}
    >
      {cloneElement(children, { 'aria-describedby': describedBy })}
      <TooltipBubble id={id} hidden={!open} className={cx(styles.bubble, styles[placement], styles[align])}>
        {label}
      </TooltipBubble>
    </span>
  );
}

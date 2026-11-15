import type { ComponentProps } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './WeekCell.module.css';

export interface WeekCellProps extends ComponentProps<'button'> {
  /** In the schedule: filled green. */
  active: boolean;
  /** The hour it stands for, as its accessible name: "Tue 02:00–03:00". */
  label: string;
  /** Draw it only, not as a button: the Schedule page's read-only mini grid. */
  readOnly?: boolean;
}

/**
 * One hour of the schedule's week grid (components.md § Week-grid cell). A toggle button: the
 * page's grid adds click-and-drag painting with pointer events (web-ui.md § Schedule modal), and
 * shows the hour in ui-b's tooltip on hover.
 */
export function WeekCell({ active, label, readOnly = false, className, type = 'button', ...rest }: WeekCellProps) {
  const classes = cx(styles.cell, active && styles.active, className);
  if (readOnly) return <span className={classes} />;
  return <button {...rest} type={type} aria-pressed={active} aria-label={label} className={classes} />;
}

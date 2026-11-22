import type { ReactNode } from 'react';
import { NavLink } from 'react-router';
import { cx } from '@/lib/cx.ts';
import styles from './Chip.module.css';

export interface ChipLinkProps {
  /** The page it opens: '/history/runs'. */
  to: string;
  /** Only on for exactly this path, not the paths under it. */
  end?: boolean;
  children: ReactNode;
  className?: string;
}

/**
 * A chip that is a link, on while its page is open: History's Runs · Tracks · Logs tabs, which
 * web-ui.md § History styles "like the client's filter chips". The open one gets
 * aria-current="page".
 */
export function ChipLink({ to, end, children, className }: ChipLinkProps) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => cx(styles.chip, isActive && styles.on, className)}>
      {children}
    </NavLink>
  );
}

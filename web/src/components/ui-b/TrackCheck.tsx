import { TrackBadge, type TrackBadgeProps } from '@/components/ui-a';
import { Tooltip } from './Tooltip.tsx';

/** What tracking means, in the check's tooltip: it's about the scheduled backups, not a download. */
export const TRACKED_HINT = 'Tracked: included in scheduled backups';
export const NOT_TRACKED_HINT = 'Not tracked: left out of scheduled backups';

export interface TrackCheckProps extends TrackBadgeProps {
  /** Which edge the tooltip lines up with: 'start' at a row's left edge, 'end' at a card's right. */
  align?: 'center' | 'start' | 'end';
}

/**
 * Tracking an item: ui-a's TrackBadge (the round check) with a tooltip that says what it does.
 * The grid card's corner badge, a list row's first column and the detail header (`inline`).
 */
export function TrackCheck({ align = 'center', ...badge }: TrackCheckProps) {
  return (
    <Tooltip label={badge.tracked ? TRACKED_HINT : NOT_TRACKED_HINT} align={align}>
      <TrackBadge {...badge} />
    </Tooltip>
  );
}
